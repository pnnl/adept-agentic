#!/usr/bin/env python3
"""
Keycloak User Management Script

OVERVIEW:
This script manages Keycloak user creation and updates for the ADEPT framework.
It provides a simple CLI interface to add users with notebook-user-like permissions.

KEY FEATURES:
1. User Creation - Create new users with specified groups and credentials
2. User Updates - Update existing user groups and passwords
3. Group Validation - Verify groups exist before user creation
4. Email Verification - Automatically verify user emails
5. Dry-Run Mode - Preview changes without applying them

COMMON USE CASES:
- Add new scientist/engineer users with notebook-users group
- Add admin users with admin group
- Add multi-group users (e.g., notebook-users,streamlit-users)
- Update existing user passwords or group memberships

RELATED DOCUMENTATION:
- docs/PLATFORM_AI_ENGINEER_ONBOARDING.md - User onboarding process
- scripts/deps/bootstrap_keycloak.py - Initial Keycloak setup
- scripts/deps/README.md - Script documentation

ENVIRONMENT VARIABLES:
- KC_ADMIN_CLI_SECRET: Admin-CLI client secret (required)
- KC_BOOTSTRAP_ADMIN_USERNAME: Keycloak admin username (default: admin)
- KC_BOOTSTRAP_ADMIN_PASSWORD: Keycloak admin password (default: admin)

USAGE:
    # Add new user with notebook-users group
    python scripts/deps/add_keycloak_user.py \\
        --username alice \\
        --password alice-password \\
        --groups notebook-users \\
        --email alice@example.com

    # Add user with multiple groups
    python scripts/deps/add_keycloak_user.py \\
        --username bob \\
        --password bob-password \\
        --groups notebook-users,streamlit-users \\
        --email bob@example.com

    # Update existing user (add to admin group)
    python scripts/deps/add_keycloak_user.py \\
        --username alice \\
        --groups notebook-users,admin \\
        --update

    # List available groups
    python scripts/deps/add_keycloak_user.py --list-groups

    # Dry-run mode (preview changes)
    python scripts/deps/add_keycloak_user.py \\
        --username test-user \\
        --password test-pass \\
        --groups notebook-users \\
        --dry-run

VALIDATION:
After adding a user, verify authentication:
    # Test user login
    export KEYCLOAK_USERNAME=alice
    export KEYCLOAK_PASSWORD=alice-password
    python examples/scripts/validate-langgraph-examples.py

MAKEFILE INTEGRATION:
    # Use convenient make target
    make add-user USERNAME=alice PASSWORD=alice-password GROUPS=notebook-users
"""
import argparse
import os
import re
import sys
import time
from typing import List, Optional

from keycloak import KeycloakAdmin, KeycloakOpenIDConnection

# --- Add src to path to import core utilities ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))
from agentic_framework_pkg.core.secrets_manager import get_secret
from agentic_framework_pkg.logger_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# KEYCLOAK CONNECTION
# =============================================================================


def get_keycloak_admin_client() -> Optional[KeycloakAdmin]:
    """
    Establishes a connection with the Keycloak server and returns an admin client.

    Returns:
        KeycloakAdmin client or None if connection fails
    """
    # CRITICAL: admin-cli is a confidential client requiring a client secret
    admin_cli_secret = get_secret("KC_ADMIN_CLI_SECRET")

    if not admin_cli_secret:
        logger.error(
            "KC_ADMIN_CLI_SECRET not found in credentials directory or environment variables."
        )
        logger.error(
            "The admin-cli client is configured as a confidential client and requires a client secret."
        )
        logger.error(
            "To discover the secret, run: ./scripts/deps/discover_admin_cli_secret.sh"
        )
        logger.error(
            "Then save to /app/credentials/KC_ADMIN_CLI_SECRET or add to .env file."
        )
        return None

    keycloak_connection = KeycloakOpenIDConnection(
        server_url="http://keycloak:8180/",
        username=os.getenv("KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        password=os.getenv("KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"),
        realm_name="master",
        user_realm_name="master",
        verify=True,
        client_secret_key=admin_cli_secret,
    )

    for i in range(10):
        try:
            admin_client = KeycloakAdmin(connection=keycloak_connection)
            admin_client.get_realms()  # Test connection
            logger.info("Successfully connected to Keycloak.")
            return admin_client
        except Exception as e:
            logger.warning(
                f"Could not connect to Keycloak, retrying in 5 seconds... ({e})"
            )
            time.sleep(5)

    logger.error("Failed to connect to Keycloak after multiple retries.")
    return None


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================


def validate_username(username: str) -> bool:
    """
    Validate username format.

    Rules:
    - 3-64 characters
    - Alphanumeric, hyphens, underscores only
    - Cannot start/end with hyphen or underscore

    Args:
        username: Username to validate

    Returns:
        True if valid, False otherwise
    """
    if not username or len(username) < 3 or len(username) > 64:
        logger.error(f"Username must be 3-64 characters long (got: {len(username)})")
        return False

    if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9_-]*[a-zA-Z0-9])?$", username):
        logger.error(
            "Username must be alphanumeric with optional hyphens/underscores (cannot start/end with special chars)"
        )
        return False

    return True


def validate_password(password: str) -> bool:
    """
    Validate password strength.

    Rules:
    - Minimum 8 characters
    - Recommended: Mix of uppercase, lowercase, numbers, symbols

    Args:
        password: Password to validate

    Returns:
        True if valid, False otherwise
    """
    if not password or len(password) < 8:
        logger.error("Password must be at least 8 characters long")
        return False

    # Check complexity (warn only, don't fail)
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)

    complexity_score = sum([has_upper, has_lower, has_digit, has_special])

    if complexity_score < 2:
        logger.warning(
            "⚠️  Weak password detected. Recommended: mix of uppercase, lowercase, numbers, and symbols."
        )

    return True


def validate_email(email: str) -> bool:
    """
    Validate email format.

    Args:
        email: Email to validate

    Returns:
        True if valid, False otherwise
    """
    if not email:
        logger.error("Email is required")
        return False

    # Basic email regex (RFC 5322 simplified)
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_pattern, email):
        logger.error(f"Invalid email format: {email}")
        return False

    return True


def validate_groups_exist(
    admin_client: KeycloakAdmin, group_names: List[str]
) -> bool:
    """
    Validate that all specified groups exist in Keycloak.

    Args:
        admin_client: Keycloak admin client
        group_names: List of group names to validate

    Returns:
        True if all groups exist, False otherwise
    """
    try:
        all_groups = admin_client.get_groups()
        existing_group_names = {g["name"] for g in all_groups}

        missing_groups = [g for g in group_names if g not in existing_group_names]

        if missing_groups:
            logger.error(
                f"Groups do not exist in Keycloak: {', '.join(missing_groups)}"
            )
            logger.info(
                f"Available groups: {', '.join(sorted(existing_group_names))}"
            )
            return False

        return True
    except Exception as e:
        logger.error(f"Failed to validate groups: {e}")
        return False


# =============================================================================
# USER MANAGEMENT FUNCTIONS
# =============================================================================


def list_available_groups(admin_client: KeycloakAdmin) -> None:
    """
    List all available groups in Keycloak.

    Args:
        admin_client: Keycloak admin client
    """
    try:
        all_groups = admin_client.get_groups()
        group_names = sorted([g["name"] for g in all_groups])

        print("\n" + "=" * 60)
        print("Available Keycloak Groups")
        print("=" * 60)

        if not group_names:
            print("No groups found.")
        else:
            for i, group_name in enumerate(group_names, 1):
                print(f"  {i}. {group_name}")

        print("=" * 60)
        print(
            f"\nTotal groups: {len(group_names)}\n"
        )

    except Exception as e:
        logger.error(f"Failed to list groups: {e}")
        sys.exit(1)


def create_or_update_user(
    admin_client: KeycloakAdmin,
    username: str,
    password: Optional[str],
    email: str,
    groups: List[str],
    update_existing: bool = False,
    dry_run: bool = False,
) -> bool:
    """
    Create a new user or update an existing user in Keycloak.

    Args:
        admin_client: Keycloak admin client
        username: Username for the new user
        password: Password (required for new users, optional for updates)
        email: Email address
        groups: List of group names to assign user to
        update_existing: If True, update existing user instead of failing
        dry_run: If True, preview changes without applying them

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if user already exists
        existing_users = admin_client.get_users({"username": username})

        if existing_users:
            if not update_existing:
                logger.error(
                    f"User '{username}' already exists. Use --update flag to modify existing user."
                )
                return False

            # Update existing user
            user_id = existing_users[0]["id"]

            if dry_run:
                print(f"\n[DRY-RUN] Would update existing user '{username}':")
                print(f"  - User ID: {user_id}")
                print(f"  - Email: {email} (verified)")
                if password:
                    print(f"  - Password: [would be updated]")
                print(f"  - Groups: {', '.join(groups)}")
                return True

            logger.info(f"Updating existing user: {username}")

            # Update user details
            admin_client.update_user(
                user_id, {"email": email, "emailVerified": True, "enabled": True}
            )
            logger.info(f"Updated user '{username}' with verified email.")

            # Update password if provided
            if password:
                admin_client.set_user_password(user_id, password, temporary=False)
                logger.info(f"Updated password for user '{username}'.")

            # Update groups
            all_groups = admin_client.get_groups()
            group_name_to_id = {g["name"]: g["id"] for g in all_groups}

            current_user_groups = admin_client.get_user_groups(user_id=user_id)
            current_group_ids = {g["id"] for g in current_user_groups}

            for group_name in groups:
                group_id = group_name_to_id[group_name]
                if group_id not in current_group_ids:
                    admin_client.group_user_add(user_id, group_id)
                    logger.info(
                        f"Added user '{username}' to group '{group_name}'."
                    )
                else:
                    logger.info(
                        f"User '{username}' is already in group '{group_name}'."
                    )

            print(
                f"\n✅ Successfully updated user '{username}' with groups: {', '.join(groups)}"
            )
            return True

        # Create new user
        if not password:
            logger.error("Password is required for new user creation")
            return False

        if dry_run:
            print(f"\n[DRY-RUN] Would create new user '{username}':")
            print(f"  - Username: {username}")
            print(f"  - Email: {email} (verified)")
            print(f"  - Password: [would be set]")
            print(f"  - Groups: {', '.join(groups)}")
            print(f"  - Enabled: True")
            return True

        logger.info(f"Creating new user: {username}")

        # Create user
        user_id = admin_client.create_user(
            {
                "username": username,
                "enabled": True,
                "email": email,
                "emailVerified": True,
            }
        )

        logger.info(f"Created user '{username}' with ID: {user_id}")

        # Set password
        admin_client.set_user_password(user_id, password, temporary=False)
        logger.info(f"Set password for user '{username}'.")

        # Assign to groups
        all_groups = admin_client.get_groups()
        group_name_to_id = {g["name"]: g["id"] for g in all_groups}

        for group_name in groups:
            group_id = group_name_to_id[group_name]
            admin_client.group_user_add(user_id, group_id)
            logger.info(f"Assigned user '{username}' to group '{group_name}'.")

        print(
            f"\n✅ Successfully created user '{username}' with groups: {', '.join(groups)}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to create/update user '{username}': {e}")
        return False


# =============================================================================
# CLI INTERFACE
# =============================================================================


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Keycloak User Management Script for ADEPT Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create user with notebook-users group
  %(prog)s --username alice --password alice-password --groups notebook-users --email alice@example.com

  # Create user with multiple groups
  %(prog)s --username bob --password bob-pass --groups notebook-users,streamlit-users --email bob@example.com

  # Update existing user (add to admin group)
  %(prog)s --username alice --groups notebook-users,admin --update

  # List available groups
  %(prog)s --list-groups

  # Dry-run mode (preview changes)
  %(prog)s --username test --password test --groups notebook-users --dry-run

For more information, see: scripts/deps/README.md
        """,
    )

    parser.add_argument(
        "--username",
        type=str,
        help="Username for the user (3-64 alphanumeric chars, hyphens, underscores)",
    )

    parser.add_argument(
        "--password",
        type=str,
        help="Password for the user (min 8 chars, required for new users)",
    )

    parser.add_argument(
        "--email",
        type=str,
        help="Email address for the user (will be verified automatically)",
    )

    parser.add_argument(
        "--groups",
        type=str,
        help='Comma-separated list of groups (e.g., "notebook-users,admin")',
    )

    parser.add_argument(
        "--update",
        action="store_true",
        help="Update existing user instead of failing if user already exists",
    )

    parser.add_argument(
        "--list-groups",
        action="store_true",
        help="List all available groups in Keycloak and exit",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )

    return parser.parse_args()


def main():
    """Main entry point for user management script."""
    args = parse_args()

    # Connect to Keycloak
    admin_client = get_keycloak_admin_client()
    if not admin_client:
        logger.error("Failed to connect to Keycloak. Exiting.")
        sys.exit(1)

    # List groups and exit
    if args.list_groups:
        list_available_groups(admin_client)
        sys.exit(0)

    # Validate required arguments for user creation/update
    if not args.username:
        logger.error("--username is required (or use --list-groups)")
        sys.exit(1)

    if not args.groups:
        logger.error("--groups is required (e.g., --groups notebook-users)")
        sys.exit(1)

    if not args.update and not args.password:
        logger.error("--password is required for new user creation")
        sys.exit(1)

    if not args.email:
        # Auto-generate email from username
        args.email = f"{args.username}@example.com"
        logger.info(f"Auto-generated email: {args.email}")

    # Validate inputs
    if not validate_username(args.username):
        sys.exit(1)

    if args.password and not validate_password(args.password):
        sys.exit(1)

    if not validate_email(args.email):
        sys.exit(1)

    # Parse groups
    group_list = [g.strip() for g in args.groups.split(",") if g.strip()]
    if not group_list:
        logger.error("No valid groups specified")
        sys.exit(1)

    # Validate groups exist
    if not validate_groups_exist(admin_client, group_list):
        sys.exit(1)

    # Create or update user
    success = create_or_update_user(
        admin_client=admin_client,
        username=args.username,
        password=args.password,
        email=args.email,
        groups=group_list,
        update_existing=args.update,
        dry_run=args.dry_run,
    )

    if not success:
        sys.exit(1)

    # Print next steps
    if not args.dry_run:
        print("\n" + "=" * 60)
        print("Next Steps")
        print("=" * 60)
        print(f"1. Test authentication with new user:")
        print(f"   export KEYCLOAK_USERNAME={args.username}")
        if args.password:
            print(f"   export KEYCLOAK_PASSWORD={args.password}")
        print(f"   python examples/scripts/validate-langgraph-examples.py")
        print()
        print(f"2. View user details in Keycloak UI:")
        print(f"   https://api.agentic.local/admin/master/console/#/master/users")
        print()
        print(f"3. Verify group memberships:")
        print(f"   Groups: {', '.join(group_list)}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
