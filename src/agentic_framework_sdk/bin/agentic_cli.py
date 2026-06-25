#!/usr/bin/env python3
"""
Agentic Framework CLI - Direct Python Entry Point
Replaces the bash wrapper with a proper Python implementation.
"""

import os
import sys
import subprocess
import json
from pathlib import Path
import tempfile
import requests
import asyncio
import httpx

# Colors for output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color

def log_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.NC}")

def log_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.NC}")

def log_warning(msg):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.NC}")

def log_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.NC}")

def check_hosts_file():
    """Check if /etc/hosts has the required entry"""
    hosts_file = "/etc/hosts"
    required_host = "api.agentic.local"
    
    log_info("Checking /etc/hosts file...")
    
    try:
        with open(hosts_file, 'r') as f:
            content = f.read()
        
        if f"127.0.0.1" in content and required_host in content:
            log_success(f"Host entry found: {required_host}")
            return True
        else:
            log_error(f"Host entry missing: {required_host}")
            print(f"\nTo fix this, run:")
            print(f"  sudo echo '127.0.0.1 {required_host}' >> /etc/hosts\n")
            return False
    except Exception as e:
        log_error(f"Failed to check hosts file: {e}")
        return False

def check_docker_services():
    """Check if required Docker services are running"""
    log_info("Checking required Docker services...")
    
    required_services = ["nginx_proxy", "keycloak", "agent_gateway"]
    
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, check=True
        )
        running_services = result.stdout.strip().split('\n')
        
        all_running = True
        for service in required_services:
            if any(service in running_service for running_service in running_services):
                log_success(f"Service running: {service}")
            else:
                log_error(f"Service not running: {service}")
                all_running = False
        
        return all_running
    except Exception as e:
        log_error(f"Failed to check Docker services: {e}")
        return False

def check_nginx_connectivity():
    """Check if NGINX proxy is accessible"""
    log_info("Testing NGINX proxy connectivity...")
    
    try:
        response = requests.get("https://api.agentic.local/health", 
                              verify=False, timeout=10)
        if response.status_code == 200:
            log_success("NGINX proxy is accessible")
            return True
        else:
            log_error(f"NGINX proxy returned status {response.status_code}")
            return False
    except Exception as e:
        log_error(f"NGINX proxy not accessible: {e}")
        return False

def check_auth_endpoint():
    """Check if authentication endpoint is accessible"""
    log_info("Testing authentication endpoint...")
    
    try:
        # Test a simple endpoint that doesn't require auth
        response = requests.get("https://api.agentic.local/auth/.well-known/openid_configuration", 
                              verify=False, timeout=10)
        # 404 is expected here since this endpoint is broken, but it means we can reach Keycloak
        if response.status_code in [200, 404]:
            log_success("Authentication endpoint is accessible")
            return True
        else:
            log_error(f"Authentication endpoint returned status {response.status_code}")
            return False
    except Exception as e:
        log_error(f"Authentication endpoint not accessible: {e}")
        return False

def check_python_environment():
    """Check if Python environment has required modules"""
    log_info("Checking Python environment...")
    
    try:
        # Check if agentic_framework_sdk is available
        from agentic_framework_sdk.cli.main import cli
        log_success("Python CLI modules available")
        return True
    except ImportError as e:
        log_error(f"Python modules missing: {e}")
        return False

async def initialize_external_cli():
    """Initialize external CLI authentication and configuration"""
    log_info("Starting external CLI initialization...")
    
    # Create .adept-agentic directory
    agentic_dir = Path.home() / '.adept-agentic'
    agentic_dir.mkdir(exist_ok=True)
    
    try:
        # Step 1: Generate authentication token
        log_info("Generating authentication token via NGINX proxy...")
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            response = await client.post(
                'https://api.agentic.local/auth/protocol/openid-connect/token',
                data={
                    'grant_type': 'password',
                    'client_id': 'login-client',
                    'username': 'notebook-user',
                    'password': 'password'
                }
            )
            
            if response.status_code != 200:
                log_error(f"Token generation failed: {response.status_code} - {response.text}")
                return False
            
            token_data = response.json()
            log_success("Authentication token generated successfully")
        
        # Step 2: Save tokens
        tokens_file = agentic_dir / 'tokens.json'
        tokens_data = {
            'default': {
                'access_token': token_data['access_token'],
                'expires_in': token_data['expires_in'],
                'refresh_expires_in': token_data['refresh_expires_in'],
                'refresh_token': token_data['refresh_token'],
                'token_type': token_data['token_type'],
                'not-before-policy': token_data['not-before-policy'],
                'session_state': token_data['session_state'],
                'scope': token_data['scope'],
                'stored_at': int(response.elapsed.total_seconds() * 1000)
            }
        }
        
        with open(tokens_file, 'w') as f:
            json.dump(tokens_data, f, indent=2)
        log_success(f"Tokens saved to: {tokens_file}")
        
        # Step 3: Save CLI configuration
        config_file = agentic_dir / 'config.json'
        config_data = {
            'gateway_url': 'https://api.agentic.local/v1',
            'model': 'agentic-framework:scientific-agent-v1',
            'api_key': token_data['access_token'],
            'username': 'notebook-user',
            'default_session_prefix': 'cli-session',
            'auto_save': True,
            'stream': True
        }
        
        with open(config_file, 'w') as f:
            json.dump(config_data, f, indent=2)
        log_success(f"Configuration saved to: {config_file}")
        
        # Step 4: Test authentication
        log_info("Testing authentication...")
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            headers = {'Authorization': f"Bearer {token_data['access_token']}"}
            response = await client.get('https://api.agentic.local/v1/models', headers=headers)
            
            if response.status_code == 200:
                models = response.json().get('data', [])
                log_success(f"Authentication test passed - {len(models)} models available")
                for model in models[:3]:  # Show first 3 models
                    log_info(f"  📦 Model: {model['id']}")
            else:
                log_error(f"Authentication test failed: {response.status_code}")
                return False
        
        log_success("🎉 External CLI initialization completed successfully!")
        log_info("You can now use: agentic-cli auth test --external")
        log_info("Or start chatting with: agentic-cli chat")
        return True
        
    except Exception as e:
        log_error(f"Initialization failed: {e}")
        return False

def validate_environment():
    """Run all environment validation checks"""
    print("🚀 Agentic Framework CLI Setup & Validation")
    print("============================================\n")
    
    checks = [
        check_hosts_file,
        check_docker_services,
        check_nginx_connectivity,
        check_auth_endpoint,
        check_python_environment
    ]
    
    all_passed = True
    for check in checks:
        if not check():
            all_passed = False
        print()  # Add spacing between checks
    
    if all_passed:
        log_success("Environment validation passed!")
        return True
    else:
        log_error("Environment validation failed!")
        return False

def run_cli(args):
    """Run the actual CLI with proper module invocation"""
    log_info("Starting Agentic CLI...")
    
    if not validate_environment():
        sys.exit(1)
    
    log_info("Running CLI with provided arguments...")
    
    try:
        # Import and run the CLI function
        from agentic_framework_sdk.cli.main import cli as cli_main
        
        # Temporarily modify sys.argv to pass arguments
        original_argv = sys.argv.copy()
        sys.argv = ['agentic-cli'] + args
        
        try:
            cli_main()
        finally:
            sys.argv = original_argv
            
    except ImportError as e:
        log_error(f"Failed to import CLI module: {e}")
        # Fallback to subprocess call
        try:
            cmd = [sys.executable, "-m", "agentic_framework_sdk.cli.main"] + args
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            log_error(f"CLI execution failed: {e}")
            sys.exit(1)
    except Exception as e:
        log_error(f"CLI execution failed: {e}")
        sys.exit(1)

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        prog='agentic-cli',
        description='Agentic Framework CLI with environment validation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  agentic-cli --check                           # Validate environment only
  agentic-cli --init                            # Initialize external CLI setup
  agentic-cli auth login --external --username notebook-user
  agentic-cli auth test --external
  agentic-cli chat
  agentic-cli chat --no-stream
        '''
    )
    
    parser.add_argument('--check', action='store_true',
                       help='Validate environment only')
    parser.add_argument('--init', action='store_true',
                       help='Initialize external CLI authentication and configuration')
    
    # Parse known args to separate validation from CLI args
    known_args, unknown_args = parser.parse_known_args()
    
    if known_args.check:
        # Only run validation
        success = validate_environment()
        sys.exit(0 if success else 1)
    elif known_args.init:
        # Run initialization
        print("🚀 Initializing External CLI Setup")
        print("==================================\n")
        
        # First validate environment
        if not validate_environment():
            log_error("Environment validation failed. Please fix issues before initializing.")
            sys.exit(1)
        
        # Run initialization
        success = asyncio.run(initialize_external_cli())
        sys.exit(0 if success else 1)
    else:
        # Run CLI with all arguments
        run_cli(unknown_args)

if __name__ == "__main__":
    main()