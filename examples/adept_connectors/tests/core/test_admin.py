"""Tests for user provisioning — Pydantic models, password generation, formatting.

Tests mock KeycloakAdmin to avoid needing a running Keycloak instance.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from pydantic import ValidationError

from adept_connectors.core.admin.user_provisioning import (
    ProvisionRequest,
    ProvisionResult,
    ProvisionStatus,
    UserEmail,
    _is_valid_email,
    format_results_csv,
    format_results_json,
    format_results_table,
    generate_password,
    provision_users,
)


# ── Password Generation ─────────────────────────────────────────────


class TestPasswordGeneration:

    def test_default_length(self):
        pw = generate_password()
        assert len(pw) == 16

    def test_custom_length(self):
        pw = generate_password(length=32)
        assert len(pw) == 32

    def test_uniqueness(self):
        passwords = {generate_password() for _ in range(100)}
        assert len(passwords) == 100  # all unique


# ── Email Validation ─────────────────────────────────────────────────


class TestEmailValidation:

    def test_valid_emails(self):
        assert _is_valid_email("alice@pnnl.gov")
        assert _is_valid_email("bob.smith@ornl.gov")
        assert _is_valid_email("user@example.co.uk")

    def test_invalid_emails(self):
        assert not _is_valid_email("not-an-email")
        assert not _is_valid_email("@missing.com")
        assert not _is_valid_email("user@")
        assert not _is_valid_email("")


# ── Pydantic Models ──────────────────────────────────────────────────


class TestPydanticModels:

    def test_user_email_valid(self):
        user = UserEmail(email="alice@pnnl.gov")
        assert user.email == "alice@pnnl.gov"

    def test_user_email_strips_whitespace(self):
        user = UserEmail(email="  bob@ornl.gov  ")
        assert user.email == "bob@ornl.gov"

    def test_user_email_rejects_invalid(self):
        with pytest.raises(ValidationError, match="Invalid email"):
            UserEmail(email="not-an-email")

    def test_user_email_rejects_empty(self):
        with pytest.raises(ValidationError):
            UserEmail(email="")

    def test_provision_request_valid(self):
        req = ProvisionRequest(
            emails=["alice@pnnl.gov", "bob@ornl.gov"],
            admin_password="secret",
        )
        assert len(req.emails) == 2
        assert req.group == "notebook-users"
        assert req.temporary_password is False

    def test_provision_request_requires_emails(self):
        with pytest.raises(ValidationError):
            ProvisionRequest(emails=[], admin_password="secret")

    def test_provision_request_requires_password(self):
        with pytest.raises(ValidationError):
            ProvisionRequest(emails=["alice@pnnl.gov"], admin_password="")

    def test_provision_result_created(self):
        result = ProvisionResult(
            email="alice@pnnl.gov",
            username="alice@pnnl.gov",
            password="xK9mLp2vQ7aB3cD4",
            status=ProvisionStatus.CREATED,
            group="notebook-users",
        )
        d = result.to_dict()
        assert d["status"] == "created"
        assert d["password"] == "xK9mLp2vQ7aB3cD4"

    def test_provision_result_already_exists(self):
        result = ProvisionResult(
            email="bob@pnnl.gov",
            username="bob@pnnl.gov",
            status=ProvisionStatus.ALREADY_EXISTS,
            group="notebook-users",
        )
        assert result.password is None

    def test_provision_result_from_dict(self):
        d = {"email": "a@b.com", "username": "a@b.com", "password": "pw",
             "status": "created", "group": "users"}
        result = ProvisionResult(**d)
        assert result.status == ProvisionStatus.CREATED


# ── Provisioning (mocked Keycloak) ──────────────────────────────────


class TestProvisionUsers:

    @pytest.fixture
    def mock_keycloak(self):
        """Mock the keycloak module so provision_users' lazy import works."""
        mock_module = MagicMock()
        admin_instance = mock_module.KeycloakAdmin.return_value
        admin_instance.get_groups.return_value = [
            {"id": "g-1", "name": "notebook-users"},
            {"id": "g-2", "name": "admin"},
        ]
        admin_instance.get_users.return_value = []  # no existing users
        admin_instance.create_user.return_value = "new-user-id"

        with patch.dict("sys.modules", {"keycloak": mock_module}):
            yield admin_instance

    def _import_and_provision(self, emails, **kwargs):
        """Import with mocked keycloak module available."""
        return provision_users(emails, admin_password="test", **kwargs)

    def test_provision_single_user(self, mock_keycloak):
        results = self._import_and_provision(["alice@pnnl.gov"])
        assert len(results) == 1
        assert results[0]["status"] == "created"
        assert results[0]["email"] == "alice@pnnl.gov"
        assert results[0]["password"] is not None
        assert len(results[0]["password"]) == 16
        mock_keycloak.create_user.assert_called_once()
        mock_keycloak.set_user_password.assert_called_once()
        mock_keycloak.group_user_add.assert_called_once_with("new-user-id", "g-1")

    def test_provision_multiple_users(self, mock_keycloak):
        mock_keycloak.create_user.side_effect = ["uid-1", "uid-2", "uid-3"]
        results = self._import_and_provision([
            "alice@pnnl.gov", "bob@ornl.gov", "carol@lbl.gov"
        ])
        assert len(results) == 3
        assert all(r["status"] == "created" for r in results)
        assert len({r["password"] for r in results}) == 3  # unique passwords

    def test_skip_existing_user(self, mock_keycloak):
        mock_keycloak.get_users.side_effect = [
            [{"id": "existing-id"}],  # alice exists
            [],                        # bob doesn't
        ]
        mock_keycloak.create_user.return_value = "new-bob-id"
        results = self._import_and_provision(["alice@pnnl.gov", "bob@pnnl.gov"])
        assert results[0]["status"] == "already_exists"
        assert results[0]["password"] is None
        assert results[1]["status"] == "created"

    def test_skip_invalid_email(self, mock_keycloak):
        results = self._import_and_provision(["not-an-email", "alice@pnnl.gov"])
        assert results[0]["status"] == "skipped_invalid"
        assert results[1]["status"] == "created"

    def test_skip_empty_lines(self, mock_keycloak):
        results = self._import_and_provision(["", "  ", "alice@pnnl.gov"])
        assert results[0]["status"] == "skipped_invalid"
        assert results[1]["status"] == "skipped_invalid"
        assert results[2]["status"] == "created"

    def test_temporary_password(self, mock_keycloak):
        self._import_and_provision(["alice@pnnl.gov"], temporary_password=True)
        mock_keycloak.set_user_password.assert_called_once()
        call_args = mock_keycloak.set_user_password.call_args
        assert call_args[0][0] == "new-user-id"
        assert call_args[0][1] is not None  # password
        assert call_args[1].get("temporary", call_args[0][2] if len(call_args[0]) > 2 else None) is True

    def test_custom_group(self, mock_keycloak):
        mock_keycloak.get_groups.return_value = [
            {"id": "g-admin", "name": "admin"},
        ]
        results = self._import_and_provision(["alice@pnnl.gov"], group="admin")
        mock_keycloak.group_user_add.assert_called_once_with("new-user-id", "g-admin")
        assert results[0]["group"] == "admin"

    def test_missing_group(self, mock_keycloak):
        mock_keycloak.get_groups.return_value = []  # no groups
        results = self._import_and_provision(["alice@pnnl.gov"])
        assert results[0]["status"] == "created"
        mock_keycloak.group_user_add.assert_not_called()


# ── Output Formatting ────────────────────────────────────────────────


class TestOutputFormatting:

    @pytest.fixture
    def sample_results(self):
        return [
            {"email": "alice@pnnl.gov", "username": "alice@pnnl.gov", "password": "xK9mLp2vQ7aB3cD4", "status": "created", "group": "notebook-users"},
            {"email": "bob@pnnl.gov", "username": "bob@pnnl.gov", "password": None, "status": "already_exists", "group": "notebook-users"},
        ]

    def test_table_format(self, sample_results):
        table = format_results_table(sample_results)
        assert "alice@pnnl.gov" in table
        assert "bob@pnnl.gov" in table
        assert "created" in table
        assert "already_exists" in table

    def test_csv_format(self, sample_results):
        csv_out = format_results_csv(sample_results)
        assert "email,username,password,status,group" in csv_out
        assert "alice@pnnl.gov" in csv_out

    def test_json_format(self, sample_results):
        json_out = format_results_json(sample_results)
        parsed = json.loads(json_out)
        assert len(parsed) == 2
        assert parsed[0]["email"] == "alice@pnnl.gov"
