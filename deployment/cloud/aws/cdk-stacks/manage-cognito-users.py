#!/usr/bin/env python3
"""
Manage AWS Cognito users for ADEPT Application Stack
Provides CLI for user management (create, delete, reset password, list)
"""

import sys
import boto3
import click
from botocore.exceptions import ClientError


def get_user_pool_id(env_label: str, user_label: str) -> str:
    """Get User Pool ID from CloudFormation stack outputs."""
    cfn = boto3.client('cloudformation')
    stack_name = f"ADE-{env_label}-{user_label}-App-Stack"

    try:
        response = cfn.describe_stacks(StackName=stack_name)
        outputs = response['Stacks'][0]['Outputs']

        for output in outputs:
            if output['OutputKey'] == 'UserPoolId':
                return output['OutputValue']

        raise ValueError(f"UserPoolId not found in stack {stack_name}")
    except ClientError as e:
        click.echo(click.style(f"Error: {e}", fg='red'))
        click.echo(f"\nEnsure the application stack '{stack_name}' is deployed.")
        sys.exit(1)


@click.group()
def cli():
    """Manage Cognito users for ADEPT Application Stack."""
    pass


@cli.command()
@click.argument('env_label')
@click.argument('user_label')
@click.argument('email')
@click.option('--temp-password', help='Temporary password (auto-generated if not provided)')
@click.option('--send-email/--no-send-email', default=True, help='Send welcome email')
def create(env_label, user_label, email, temp_password, send_email):
    """Create a new Cognito user."""
    cognito = boto3.client('cognito-idp')
    user_pool_id = get_user_pool_id(env_label, user_label)

    try:
        kwargs = {
            'UserPoolId': user_pool_id,
            'Username': email,
            'UserAttributes': [
                {'Name': 'email', 'Value': email},
                {'Name': 'email_verified', 'Value': 'true'}
            ],
            'DesiredDeliveryMediums': ['EMAIL'] if send_email else []
        }

        if temp_password:
            kwargs['TemporaryPassword'] = temp_password

        response = cognito.admin_create_user(**kwargs)

        click.echo(click.style(f"✓ User created successfully: {email}", fg='green'))
        click.echo(f"  User Pool ID: {user_pool_id}")
        click.echo(f"  Username: {email}")

        if not temp_password:
            click.echo(f"  Temporary password: <sent via email>")
        else:
            click.echo(f"  Temporary password: {temp_password}")

        click.echo("\nUser must change password on first login.")
    except ClientError as e:
        if e.response['Error']['Code'] == 'UsernameExistsException':
            click.echo(click.style(f"Error: User {email} already exists", fg='red'))
        else:
            click.echo(click.style(f"Error creating user: {e}", fg='red'))
        sys.exit(1)


@cli.command()
@click.argument('env_label')
@click.argument('user_label')
@click.argument('email')
def delete(env_label, user_label, email):
    """Delete a Cognito user."""
    cognito = boto3.client('cognito-idp')
    user_pool_id = get_user_pool_id(env_label, user_label)

    click.confirm(
        f"Are you sure you want to delete user {email}?",
        abort=True
    )

    try:
        cognito.admin_delete_user(
            UserPoolId=user_pool_id,
            Username=email
        )
        click.echo(click.style(f"✓ User deleted successfully: {email}", fg='green'))
    except ClientError as e:
        click.echo(click.style(f"Error deleting user: {e}", fg='red'))
        sys.exit(1)


@cli.command()
@click.argument('env_label')
@click.argument('user_label')
@click.argument('email')
def reset_password(env_label, user_label, email):
    """Reset user password (sends email with temp password)."""
    cognito = boto3.client('cognito-idp')
    user_pool_id = get_user_pool_id(env_label, user_label)

    try:
        cognito.admin_reset_user_password(
            UserPoolId=user_pool_id,
            Username=email
        )
        click.echo(click.style(f"✓ Password reset initiated for: {email}", fg='green'))
        click.echo("  Temporary password sent via email.")
    except ClientError as e:
        click.echo(click.style(f"Error resetting password: {e}", fg='red'))
        sys.exit(1)


@cli.command()
@click.argument('env_label')
@click.argument('user_label')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed user information')
def list(env_label, user_label, verbose):
    """List all Cognito users."""
    cognito = boto3.client('cognito-idp')
    user_pool_id = get_user_pool_id(env_label, user_label)

    try:
        response = cognito.list_users(UserPoolId=user_pool_id)
        users = response.get('Users', [])

        if not users:
            click.echo("No users found.")
            return

        click.echo(f"\nUsers in pool {user_pool_id}:")
        click.echo("-" * 100)
        click.echo(f"{'Username':<30} {'Email':<30} {'Status':<15} {'Created'}")
        click.echo("-" * 100)

        for user in users:
            username = user['Username']
            email = next((attr['Value'] for attr in user['Attributes'] if attr['Name'] == 'email'), 'N/A')
            status = user['UserStatus']
            created = user['UserCreateDate'].strftime('%Y-%m-%d %H:%M:%S')

            click.echo(f"{username:<30} {email:<30} {status:<15} {created}")

            if verbose:
                mfa = user.get('MFAOptions', [])
                if mfa:
                    click.echo(f"  MFA: Enabled ({', '.join(m['DeliveryMedium'] for m in mfa)})")
                else:
                    click.echo("  MFA: Disabled")
                click.echo("")

        click.echo("-" * 100)
        click.echo(f"Total users: {len(users)}")

    except ClientError as e:
        click.echo(click.style(f"Error listing users: {e}", fg='red'))
        sys.exit(1)


@cli.command()
@click.argument('env_label')
@click.argument('user_label')
@click.argument('email')
@click.option('--enable/--disable', default=True, help='Enable or disable user')
def toggle_user(env_label, user_label, email, enable):
    """Enable or disable a Cognito user."""
    cognito = boto3.client('cognito-idp')
    user_pool_id = get_user_pool_id(env_label, user_label)

    try:
        if enable:
            cognito.admin_enable_user(
                UserPoolId=user_pool_id,
                Username=email
            )
            click.echo(click.style(f"✓ User enabled: {email}", fg='green'))
        else:
            cognito.admin_disable_user(
                UserPoolId=user_pool_id,
                Username=email
            )
            click.echo(click.style(f"✓ User disabled: {email}", fg='green'))
    except ClientError as e:
        click.echo(click.style(f"Error toggling user: {e}", fg='red'))
        sys.exit(1)


@cli.command()
@click.argument('env_label')
@click.argument('user_label')
def info(env_label, user_label):
    """Show Cognito User Pool information."""
    cfn = boto3.client('cloudformation')
    cognito = boto3.client('cognito-idp')
    stack_name = f"ADE-{env_label}-{user_label}-App-Stack"

    try:
        # Get stack outputs
        response = cfn.describe_stacks(StackName=stack_name)
        outputs = response['Stacks'][0]['Outputs']

        output_dict = {o['OutputKey']: o['OutputValue'] for o in outputs}

        click.echo(f"\n{'='*60}")
        click.echo(f"  Cognito User Pool Information")
        click.echo(f"{'='*60}")
        click.echo(f"  Stack: {stack_name}")
        click.echo(f"  User Pool ID: {output_dict.get('UserPoolId', 'N/A')}")
        click.echo(f"  User Pool Client ID: {output_dict.get('UserPoolClientId', 'N/A')}")
        click.echo(f"  Cognito Domain: {output_dict.get('CognitoDomain', 'N/A')}")
        click.echo(f"{'='*60}\n")

        # Get user pool details
        user_pool_id = output_dict.get('UserPoolId')
        if user_pool_id:
            pool_info = cognito.describe_user_pool(UserPoolId=user_pool_id)
            pool = pool_info['UserPool']

            click.echo("Configuration:")
            click.echo(f"  MFA Configuration: {pool.get('MfaConfiguration', 'OFF')}")
            click.echo(f"  Auto-Verified Attributes: {', '.join(pool.get('AutoVerifiedAttributes', []))}")
            click.echo(f"  Username Attributes: {', '.join(pool.get('UsernameAttributes', ['username']))}")
            click.echo(f"  Created: {pool['CreationDate'].strftime('%Y-%m-%d %H:%M:%S')}")
            click.echo("")

    except ClientError as e:
        click.echo(click.style(f"Error: {e}", fg='red'))
        sys.exit(1)


if __name__ == '__main__':
    cli()
