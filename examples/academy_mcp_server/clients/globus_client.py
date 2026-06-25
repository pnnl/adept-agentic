"""
Globus Client Manager

Manages Globus SDK clients with automatic auth and token refresh.
Supports two auth modes:
  - Mode A: Confidential client (service-level, from env vars)
  - Mode B: User token delegation (per-user, from framework injection)
"""

import logging
from typing import Dict, Optional

from globus_sdk import (
    AccessTokenAuthorizer,
    ClientCredentialsAuthorizer,
    ConfidentialAppAuthClient,
    FlowsClient,
    GroupsClient,
    SearchClient,
    TransferClient,
)
from globus_sdk.scopes import (
    FlowsScopes,
    GroupsScopes,
    SearchScopes,
    TransferScopes,
)

try:
    from ..config import settings
except ImportError:
    from config import settings

logger = logging.getLogger("academy_mcp_server")

# Globus Compute uses a different import path
try:
    from globus_compute_sdk import Client as ComputeClient
except ImportError:
    ComputeClient = None


class GlobusClientManager:
    """Manages Globus SDK clients with automatic auth and token refresh."""

    def __init__(self):
        self._confidential_client: Optional[ConfidentialAppAuthClient] = None
        self._authorizers: Dict[str, ClientCredentialsAuthorizer] = {}

    @property
    def is_configured(self) -> bool:
        return bool(settings.globus_client_id and settings.globus_client_secret)

    def _get_confidential_client(self) -> ConfidentialAppAuthClient:
        if self._confidential_client is None:
            if not self.is_configured:
                raise RuntimeError(
                    "Globus not configured. Set ACADEMY_GLOBUS_CLIENT_ID "
                    "and ACADEMY_GLOBUS_CLIENT_SECRET."
                )
            self._confidential_client = ConfidentialAppAuthClient(
                client_id=settings.globus_client_id,
                client_secret=settings.globus_client_secret,
            )
        return self._confidential_client

    def _get_cc_authorizer(self, scope: str) -> ClientCredentialsAuthorizer:
        if scope not in self._authorizers:
            self._authorizers[scope] = ClientCredentialsAuthorizer(
                confidential_client=self._get_confidential_client(),
                scopes=scope,
            )
        return self._authorizers[scope]

    def _resolve_authorizer(self, scope: str, user_token: Optional[str] = None):
        if user_token:
            return AccessTokenAuthorizer(user_token)
        return self._get_cc_authorizer(scope)

    def get_transfer_client(self, user_token: Optional[str] = None) -> TransferClient:
        auth = self._resolve_authorizer(
            TransferScopes.all, user_token
        )
        return TransferClient(authorizer=auth)

    def get_search_client(self, user_token: Optional[str] = None) -> SearchClient:
        auth = self._resolve_authorizer(
            SearchScopes.all, user_token
        )
        return SearchClient(authorizer=auth)

    def get_flows_client(self, user_token: Optional[str] = None) -> FlowsClient:
        auth = self._resolve_authorizer(
            FlowsScopes.all, user_token
        )
        return FlowsClient(authorizer=auth)

    def get_groups_client(self, user_token: Optional[str] = None) -> GroupsClient:
        auth = self._resolve_authorizer(
            GroupsScopes.all, user_token
        )
        return GroupsClient(authorizer=auth)


# Module-level singleton
globus_manager = GlobusClientManager()
