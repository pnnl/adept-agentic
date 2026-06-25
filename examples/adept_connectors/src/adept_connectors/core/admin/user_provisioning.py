"""Bulk Keycloak user provisioning for ADEPT Connectors.

Admin-side tool that creates Keycloak users from an email list,
generates random passwords, and assigns users to a group.
"""

from __future__ import annotations

import csv
import io
import json
import re
import secrets
import string
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from ..config import AdminConfig


# Password alphabet: letters + digits + special chars (no ambiguous chars)
_PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%&*"
_PASSWORD_LENGTH = 16

# Simple email regex (avoids requiring email-validator package)
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


# ── Pydantic Models ─────────────────────────────────────────────────


class ProvisionStatus(str, Enum):
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    SKIPPED_INVALID = "skipped_invalid"


class UserEmail(BaseModel):
    """Validated email address for provisioning."""

    email: str = Field(..., description="User email address")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip()
        if not v or not _EMAIL_RE.match(v):
            raise ValueError(f"Invalid email address: {v!r}")
        return v


class ProvisionRequest(BaseModel):
    """Input for bulk user provisioning."""

    emails: List[str] = Field(..., min_length=1, description="Email addresses to provision")
    group: str = Field(default="notebook-users", description="Keycloak group to assign")
    keycloak_url: str = Field(default="http://localhost:8180", description="Keycloak server URL")
    realm: str = Field(default="master", description="Keycloak realm")
    admin_username: str = Field(default="admin", description="Keycloak admin username")
    admin_password: str = Field(..., min_length=1, description="Keycloak admin password")
    temporary_password: bool = Field(default=False, description="Force password change on first login")


class ProvisionResult(BaseModel):
    """Result for a single provisioned user."""

    email: str
    username: str
    password: Optional[str] = None
    status: ProvisionStatus
    group: str

    def to_dict(self) -> dict:
        return self.model_dump()


# ── Core Functions ───────────────────────────────────────────────────


def generate_password(length: int = _PASSWORD_LENGTH) -> str:
    """Generate a cryptographically secure random password."""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def provision_users(
    emails: List[str],
    group: str = "notebook-users",
    keycloak_url: str = "http://localhost:8180",
    realm: str = "master",
    admin_username: str = "admin",
    admin_password: str = "",
    temporary_password: bool = False,
) -> List[dict]:
    """Create Keycloak users with random passwords from email list.

    Args:
        emails: List of email addresses to provision.
        group: Keycloak group to assign users to.
        keycloak_url: Keycloak server URL.
        realm: Keycloak realm name.
        admin_username: Keycloak admin username.
        admin_password: Keycloak admin password.
        temporary_password: If True, user must change password on first login.

    Returns:
        List of dicts with email, username, password, status, and group fields.
    """
    try:
        from keycloak import KeycloakAdmin, KeycloakOpenIDConnection
    except ImportError:
        raise ImportError(
            "python-keycloak is required for user provisioning. "
            "Install with: pip install adept-connector-core[admin]"
        )

    connection = KeycloakOpenIDConnection(
        server_url=keycloak_url,
        username=admin_username,
        password=admin_password,
        realm_name=realm,
    )
    admin_client = KeycloakAdmin(connection=connection)

    # Resolve group ID
    group_id = None
    for g in admin_client.get_groups():
        if g["name"] == group:
            group_id = g["id"]
            break

    results: List[ProvisionResult] = []
    for raw_email in emails:
        email = raw_email.strip()

        # Validate email via regex
        if not _is_valid_email(email):
            results.append(ProvisionResult(
                email=email,
                username=email,
                password=None,
                status=ProvisionStatus.SKIPPED_INVALID,
                group=group,
            ))
            continue

        # Check if user already exists
        existing = admin_client.get_users({"username": email})
        if existing:
            results.append(ProvisionResult(
                email=email,
                username=email,
                password=None,
                status=ProvisionStatus.ALREADY_EXISTS,
                group=group,
            ))
            continue

        password = generate_password()

        # Create user (username = email for simplicity)
        user_id = admin_client.create_user({
            "username": email,
            "email": email,
            "enabled": True,
            "emailVerified": True,
        })
        admin_client.set_user_password(user_id, password, temporary=temporary_password)

        # Assign to group
        if group_id:
            admin_client.group_user_add(user_id, group_id)

        results.append(ProvisionResult(
            email=email,
            username=email,
            password=password,
            status=ProvisionStatus.CREATED,
            group=group,
        ))

    return [r.to_dict() for r in results]


def provision_users_validated(request: ProvisionRequest) -> List[ProvisionResult]:
    """Provision users using a validated ProvisionRequest model.

    This is the Pydantic-first entry point. Validates all inputs before
    connecting to Keycloak.
    """
    raw_results = provision_users(
        emails=request.emails,
        group=request.group,
        keycloak_url=request.keycloak_url,
        realm=request.realm,
        admin_username=request.admin_username,
        admin_password=request.admin_password,
        temporary_password=request.temporary_password,
    )
    return [ProvisionResult(**r) for r in raw_results]


def provision_users_from_config(
    emails: List[str],
    config: Optional[AdminConfig] = None,
    temporary_password: bool = False,
) -> List[dict]:
    """Provision users using AdminConfig for Keycloak connection details."""
    if config is None:
        config = AdminConfig()
    return provision_users(
        emails=emails,
        group=config.default_group,
        keycloak_url=config.keycloak_url,
        realm="master",
        admin_username=config.username,
        admin_password=config.password,
        temporary_password=temporary_password,
    )


# ── Output Formatting ───────────────────────────────────────────────


def format_results_table(results: List[dict]) -> str:
    """Format provisioning results as an ASCII table."""
    lines = []
    lines.append(f"{'Email':<30} {'Username':<30} {'Password':<20} {'Status':<16} {'Group':<16}")
    lines.append("-" * 112)
    for r in results:
        pw = r["password"] or "—"
        lines.append(
            f"{r['email']:<30} {r['username']:<30} {pw:<20} {r['status']:<16} {r['group']:<16}"
        )
    return "\n".join(lines)


def format_results_csv(results: List[dict]) -> str:
    """Format provisioning results as CSV."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["email", "username", "password", "status", "group"])
    writer.writeheader()
    writer.writerows(results)
    return output.getvalue()


def format_results_json(results: List[dict]) -> str:
    """Format provisioning results as JSON."""
    return json.dumps(results, indent=2)


def _is_valid_email(email: str) -> bool:
    """Validate email using regex pattern."""
    if not email:
        return False
    return bool(_EMAIL_RE.match(email))
