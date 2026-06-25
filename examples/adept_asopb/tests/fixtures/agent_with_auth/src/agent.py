import asyncio
from typing import Optional
from auth import KeycloakAuth

class SecureAgent:
    def __init__(self, auth: KeycloakAuth):
        self.auth = auth
        self.user_token: Optional[str] = None
        self.tools = []

    async def run(self, query: str, token: str):
        await self.validate_token(token)
        return f"Authorized response to: {query}"

    async def validate_token(self, token: str):
        claims = self.auth.validate_token(token)
        if not claims:
            raise ValueError("Invalid token")
        self.user_token = token

    def register_tools(self, allowed: Optional[list[str]] = None):
        all_tools = ["search", "calculator", "exec"]
        self.tools = [t for t in all_tools if allowed is None or t in allowed]
