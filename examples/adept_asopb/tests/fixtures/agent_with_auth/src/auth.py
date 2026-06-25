import jwt
import requests
from typing import Optional, Dict, Any

class KeycloakAuth:
    def __init__(self, realm_url: str):
        self.realm_url = realm_url
        self.jwks_cache: Optional[Dict[str, Any]] = None

    def validate_token(self, token: str) -> Dict[str, Any]:
        '''Validate JWT token against Keycloak JWKS.'''
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")

            jwks = self.get_jwks()
            key_data = self._find_key(jwks, kid)

            if not key_data:
                raise ValueError(f"Key {kid} not found in JWKS")

            claims = jwt.decode(
                token,
                key_data,
                algorithms=["RS256"],
                options={"verify_signature": True},
            )
            return claims
        except jwt.InvalidTokenError:
            raise ValueError("Invalid token")

    def get_jwks(self) -> Dict[str, Any]:
        '''Fetch JWKS from Keycloak realm.'''
        if self.jwks_cache:
            return self.jwks_cache

        url = f"{self.realm_url}/protocol/openid-connect/certs"
        response = requests.get(url)
        response.raise_for_status()
        self.jwks_cache = response.json()
        return self.jwks_cache

    def _find_key(self, jwks: Dict[str, Any], kid: str) -> Optional[str]:
        '''Find a key in JWKS by kid.'''
        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid:
                return key_data
        return None
