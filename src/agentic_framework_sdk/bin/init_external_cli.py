#!/usr/bin/env python3
"""
External CLI Client Initialization Script

This script sets up the complete external CLI client workflow:
1. Validates environment prerequisites
2. Generates and stores authentication tokens
3. Configures CLI client properly
4. Tests the complete workflow
"""
import json
import asyncio
import httpx
import subprocess
import sys
from pathlib import Path
import os


def log_step(step, message):
    """Log a setup step"""
    print(f"📋 Step {step}: {message}")


def log_success(message):
    """Log success"""
    print(f"✅ {message}")


def log_error(message):
    """Log error"""
    print(f"❌ {message}")


def log_info(message):
    """Log info"""
    print(f"ℹ️  {message}")


def check_prerequisites():
    """Check all prerequisites for external CLI"""
    log_step(1, "Checking prerequisites...")
    
    # Check /etc/hosts
    try:
        with open('/etc/hosts', 'r') as f:
            hosts_content = f.read()
        if 'api.agentic.local' not in hosts_content:
            log_error("Missing /etc/hosts entry for api.agentic.local")
            log_info("Add this line to /etc/hosts: 127.0.0.1 api.agentic.local")
            return False
        log_success("Host entry found: api.agentic.local")
    except Exception as e:
        log_error(f"Failed to check /etc/hosts: {e}")
        return False
    
    # Check Docker services
    required_services = ['nginx_proxy', 'keycloak', 'agent_gateway', 'orchestration_service']
    for service in required_services:
        try:
            result = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'], 
                                  capture_output=True, text=True, check=True)
            if service not in result.stdout:
                log_error(f"Required service not running: {service}")
                return False
            log_success(f"Service running: {service}")
        except subprocess.CalledProcessError:
            log_error("Failed to check Docker services")
            return False
    
    return True


async def generate_token():
    """Generate authentication token via NGINX proxy"""
    log_step(2, "Generating authentication token...")
    
    try:
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            response = await client.post(
                'https://api.agentic.local/auth/protocol/openid-connect/token',
                data={
                    'grant_type': 'password',
                    'client_id': 'login-client', 
                    'username': 'notebook-user',
                    'password': 'password'
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
        if response.status_code == 200:
            token_info = response.json()
            token_info["stored_at"] = int(asyncio.get_event_loop().time())
            
            # Verify token has correct issuer
            import jwt as pyjwt
            decoded = pyjwt.decode(token_info['access_token'], options={'verify_signature': False})
            issuer = decoded.get('iss')
            
            if 'api.agentic.local' not in issuer:
                log_error(f"Token has wrong issuer: {issuer}")
                return None
                
            log_success(f"Token generated with correct issuer: {issuer}")
            log_success(f"Token expires in: {token_info['expires_in']} seconds")
            
            return token_info
        else:
            log_error(f"Token generation failed: {response.text}")
            return None
            
    except Exception as e:
        log_error(f"Token generation error: {e}")
        return None


def setup_token_storage(token_info):
    """Set up token storage for CLI"""
    log_step(3, "Setting up token storage...")
    
    try:
        # Create .adept-agentic directory
        token_dir = Path.home() / '.adept-agentic'
        token_dir.mkdir(exist_ok=True)
        
        # Store in tokens.json (for direct API access)
        token_file = token_dir / 'tokens.json'
        tokens = {"default": token_info}
        
        with open(token_file, 'w') as f:
            json.dump(tokens, f, indent=2)
        
        log_success(f"Token stored in {token_file}")
        return True
        
    except Exception as e:
        log_error(f"Token storage failed: {e}")
        return False


def setup_cli_config(token_info):
    """Set up CLI configuration"""
    log_step(4, "Setting up CLI configuration...")
    
    try:
        config_dir = Path.home() / '.adept-agentic'
        config_file = config_dir / 'config.json'
        
        config = {
            "gateway_url": "https://api.agentic.local/v1",
            "model": "agentic-framework:scientific-agent-v1",
            "api_key": token_info['access_token'],
            "username": "notebook-user",
            "default_session_prefix": "cli-session",
            "auto_save": True,
            "stream": True
        }
        
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        log_success(f"CLI config created: {config_file}")
        return True
        
    except Exception as e:
        log_error(f"CLI config setup failed: {e}")
        return False


async def test_authentication():
    """Test authentication with direct API call"""
    log_step(5, "Testing authentication...")
    
    try:
        token_file = Path.home() / '.adept-agentic' / 'tokens.json'
        with open(token_file, 'r') as f:
            tokens = json.load(f)
        
        access_token = tokens['default']['access_token']
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
            response = await client.get("https://api.agentic.local/v1/models", headers=headers)
            
            if response.status_code == 200:
                models = response.json()
                model_count = len(models.get('data', []))
                log_success(f"Authentication successful - {model_count} models available")
                return True
            else:
                log_error(f"Authentication failed: {response.status_code} - {response.text}")
                return False
                
    except Exception as e:
        log_error(f"Authentication test failed: {e}")
        return False


def test_cli_command():
    """Test CLI command execution"""
    log_step(6, "Testing CLI command...")
    
    try:
        # Test auth status
        result = subprocess.run([
            'python3', 'agentic_cli.py', 'auth', 'status'
        ], capture_output=True, text=True, timeout=30, env={**os.environ, 'PYTHONPATH': 'src'})
        
        if result.returncode == 0 and 'Authenticated' in result.stdout:
            log_success("CLI authentication test passed")
            return True
        else:
            log_error(f"CLI test failed: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        log_error("CLI test timed out")
        return False
    except Exception as e:
        log_error(f"CLI test error: {e}")
        return False


async def main():
    """Main initialization workflow"""
    print("🚀 External CLI Client Initialization")
    print("=" * 50)
    
    # Step 1: Prerequisites
    if not check_prerequisites():
        log_error("Prerequisites check failed")
        sys.exit(1)
    
    # Step 2: Generate token
    token_info = await generate_token()
    if not token_info:
        log_error("Token generation failed")
        sys.exit(1)
    
    # Step 3: Set up token storage
    if not setup_token_storage(token_info):
        log_error("Token storage setup failed")
        sys.exit(1)
    
    # Step 4: Set up CLI config
    if not setup_cli_config(token_info):
        log_error("CLI config setup failed")
        sys.exit(1)
    
    # Step 5: Test authentication
    if not await test_authentication():
        log_error("Authentication test failed")
        sys.exit(1)
    
    # Step 6: Test CLI
    if not test_cli_command():
        log_error("CLI test failed")
        sys.exit(1)
    
    print("\n🎉 SUCCESS! External CLI client is ready!")
    print("\nYou can now use:")
    print("  python3 agentic_cli.py auth status")
    print("  echo 'Hello!' | python3 agentic_cli.py chat")
    print("  ./scripts/agentic-cli-setup.sh chat")


if __name__ == "__main__":
    asyncio.run(main())