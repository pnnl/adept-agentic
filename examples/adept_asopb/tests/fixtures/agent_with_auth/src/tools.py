from typing import Optional
from auth import KeycloakAuth

class ToolManager:
    def __init__(self, auth: KeycloakAuth):
        self.auth = auth
        self.user_token: Optional[str] = None

    def register_tools(self, agent, token: str, allowed_permissions: Optional[list[str]] = None):
        '''Register tools with ACL filtering based on user permissions.'''
        claims = self.auth.validate_token(token)
        user_perms = claims.get("permissions", [])

        all_tools = {
            "search": "web_access",
            "read_file": "file_read",
            "exec": "system_execution",
        }

        if allowed_permissions:
            agent.tools = {
                k: v for k, v in all_tools.items()
                if k in allowed_permissions and v in user_perms
            }
        else:
            agent.tools = {k: v for k, v in all_tools.items() if v in user_perms}

    def apply_acl(self, tool_name: str, token: str) -> bool:
        '''Check if user has permission to execute tool.'''
        try:
            claims = self.auth.validate_token(token)
            user_perms = claims.get("permissions", [])
            return tool_name in user_perms
        except:
            return False
