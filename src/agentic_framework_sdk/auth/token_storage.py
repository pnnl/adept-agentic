"""
Secure token storage for CLI authentication.

Stores tokens securely using the system keyring or file-based fallback.
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime, timedelta

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

from .exceptions import TokenNotFoundError


class TokenStorage:
    """Secure storage for authentication tokens."""
    
    def __init__(self, service_name: str = "agentic-framework"):
        self.service_name = service_name
        self.config_dir = Path.home() / ".agentic"
        self.token_file = self.config_dir / "tokens.json"
        
        # Create config directory if it doesn't exist
        self.config_dir.mkdir(exist_ok=True)
    
    def store_token(self, token_info: Dict[str, Any], username: str = "default") -> None:
        """
        Store authentication tokens securely.

        Args:
            token_info: Token information from OAuth2 response
            username: Username or identifier for the token
        """
        # Add timestamp for expiry tracking
        token_info["stored_at"] = int(time.time())

        if KEYRING_AVAILABLE:
            try:
                # Use system keyring (preferred)
                keyring.set_password(
                    self.service_name,
                    f"{username}_token",
                    json.dumps(token_info)
                )
                return
            except keyring.errors.NoKeyringError:
                # No keyring backend available (e.g., Docker, CI environments)
                # Fall through to file-based storage
                pass

        # Fallback to file-based storage (used when keyring unavailable or has no backend)
        self._store_token_file(token_info, username)
    
    def get_token(self, username: str = "default") -> Dict[str, Any]:
        """
        Retrieve stored authentication token.
        
        Args:
            username: Username or identifier for the token
            
        Returns:
            Token information dictionary
            
        Raises:
            TokenNotFoundError: If no token is found
        """
        if KEYRING_AVAILABLE:
            try:
                token_json = keyring.get_password(self.service_name, f"{username}_token")
                if token_json:
                    return json.loads(token_json)
            except Exception:
                pass
        
        # Try file-based storage
        return self._get_token_file(username)
    
    def delete_token(self, username: str = "default") -> None:
        """
        Delete stored authentication token.

        Args:
            username: Username or identifier for the token
        """
        if KEYRING_AVAILABLE:
            try:
                keyring.delete_password(self.service_name, f"{username}_token")
            except (keyring.errors.PasswordDeleteError, keyring.errors.NoKeyringError):
                # PasswordDeleteError: Password doesn't exist in keyring
                # NoKeyringError: No keyring backend available (Docker, CI)
                pass

        # Also try file-based storage
        self._delete_token_file(username)
    
    def is_token_valid(self, username: str = "default") -> bool:
        """
        Check if stored token exists and is not expired.
        
        Args:
            username: Username or identifier for the token
            
        Returns:
            True if token is valid and not expired
        """
        try:
            token_info = self.get_token(username)
            
            # Check if token has expiry information
            if "expires_in" in token_info and "stored_at" in token_info:
                stored_at = token_info["stored_at"]
                expires_in = token_info["expires_in"]
                current_time = int(time.time())
                
                # Add 60 second buffer to account for request time
                if current_time >= (stored_at + expires_in - 60):
                    return False
            
            # Token exists and appears valid
            return "access_token" in token_info
            
        except TokenNotFoundError:
            return False
    
    def _store_token_file(self, token_info: Dict[str, Any], username: str) -> None:
        """Store token in file-based storage (fallback)."""
        tokens = {}
        
        # Load existing tokens if file exists
        if self.token_file.exists():
            try:
                with open(self.token_file, 'r') as f:
                    tokens = json.load(f)
            except (json.JSONDecodeError, IOError):
                tokens = {}
        
        # Store new token
        tokens[username] = token_info
        
        # Write back to file with restrictive permissions
        with open(self.token_file, 'w') as f:
            json.dump(tokens, f, indent=2)
        
        # Set file permissions to user-only read/write
        os.chmod(self.token_file, 0o600)
    
    def _get_token_file(self, username: str) -> Dict[str, Any]:
        """Get token from file-based storage."""
        if not self.token_file.exists():
            raise TokenNotFoundError(f"No token found for user {username}")
        
        try:
            with open(self.token_file, 'r') as f:
                tokens = json.load(f)
            
            if username not in tokens:
                raise TokenNotFoundError(f"No token found for user {username}")
            
            return tokens[username]
            
        except (json.JSONDecodeError, IOError) as e:
            raise TokenNotFoundError(f"Failed to read token for user {username}: {e}")
    
    def _delete_token_file(self, username: str) -> None:
        """Delete token from file-based storage."""
        if not self.token_file.exists():
            return
        
        try:
            with open(self.token_file, 'r') as f:
                tokens = json.load(f)
            
            if username in tokens:
                del tokens[username]
                
                if tokens:
                    # Write back remaining tokens
                    with open(self.token_file, 'w') as f:
                        json.dump(tokens, f, indent=2)
                    os.chmod(self.token_file, 0o600)
                else:
                    # Remove file if no tokens left
                    self.token_file.unlink()
                    
        except (json.JSONDecodeError, IOError):
            pass  # Ignore errors when deleting