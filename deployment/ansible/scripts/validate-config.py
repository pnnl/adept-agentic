#!/usr/bin/env python3
"""
Validate ADEPT configuration file against JSON schema

Usage:
    python validate-config.py <config-file>

Example:
    python validate-config.py config/adept-config-dev.yml
"""

import sys
import json
import os
from pathlib import Path
import yaml
from jsonschema import validate, ValidationError, FormatChecker


def load_yaml(file_path):
    """Load YAML configuration file"""
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"✗ Error parsing YAML file: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"✗ Configuration file not found: {file_path}")
        sys.exit(1)


def load_schema(schema_path):
    """Load JSON schema file"""
    try:
        with open(schema_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"✗ Schema file not found: {schema_path}")
        print("Run this script from deployment/ansible/ directory")
        sys.exit(1)


def validate_config(config_file, schema_file):
    """Validate configuration against schema"""
    try:
        config = load_yaml(config_file)
        schema = load_schema(schema_file)

        # Validate with format checker for UUIDs, etc.
        validate(instance=config, schema=schema, format_checker=FormatChecker())

        # Print success message
        print(f"✓ Configuration valid: {config_file}")
        print(f"\n  Deployment:")
        print(f"    Name: {config['deployment']['name']}")
        print(f"    Environment: {config['deployment']['environment']}")
        print(f"    User: {config['deployment']['user']}")
        print(f"    Cloud Provider: {config['deployment']['cloud_provider'].upper()}")

        # Check for encrypted credentials
        if 'credentials' in config:
            cloud = config['deployment']['cloud_provider']
            if cloud in config['credentials']:
                creds = config['credentials'][cloud]
                print(f"\n  Credentials:")
                if cloud == 'aws':
                    print(f"    Account ID: {creds.get('account_id', 'Not set')}")
                    print(f"    Region: {creds.get('region', 'Not set')}")
                    print(f"    Access Key: {'[ENCRYPTED]' if 'access_key_id' in creds else 'Not set'}")
                elif cloud == 'azure':
                    print(f"    Subscription ID: {creds.get('subscription_id', 'Not set')[:8]}...")
                    print(f"    Tenant ID: {creds.get('tenant_id', 'Not set')[:8]}...")
                    print(f"    Client Secret: {'[ENCRYPTED]' if 'client_secret' in creds else 'Not set'}")
                elif cloud == 'gcp':
                    print(f"    Project ID: {creds.get('project_id', 'Not set')}")
                    print(f"    Region: {creds.get('region', 'Not set')}")
                    print(f"    Credentials: {'[ENCRYPTED]' if 'credentials_json' in creds else 'Not set'}")

        return 0

    except ValidationError as e:
        print(f"✗ Configuration validation failed:")
        print(f"\n  Error at: {' -> '.join(str(p) for p in e.absolute_path)}")
        print(f"  Message: {e.message}")

        if e.validator == 'required':
            print(f"\n  Missing required field(s): {e.message}")
        elif e.validator == 'enum':
            print(f"\n  Invalid value. Expected one of: {e.validator_value}")
        elif e.validator == 'pattern':
            print(f"\n  Value does not match required pattern: {e.validator_value}")

        return 1

    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return 1


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: validate-config.py <config-file>")
        print("\nExample:")
        print("  python validate-config.py config/adept-config-dev.yml")
        sys.exit(1)

    config_file = sys.argv[1]

    # Find schema file relative to script location
    script_dir = Path(__file__).parent
    schema_file = script_dir.parent / "config" / "schemas" / "adept-config-schema.json"

    if not schema_file.exists():
        print(f"✗ Schema file not found: {schema_file}")
        sys.exit(1)

    sys.exit(validate_config(config_file, str(schema_file)))


if __name__ == "__main__":
    main()
