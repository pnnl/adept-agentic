"""
Identity Mapper: ADEPT/Globus -> Slurm Username
===============================================

Maps authenticated user identities from ADEPT JWT claims
(including Globus-federated identities) to Slurm usernames
for job submission and resource access.

Mapping priority:
1. JWT custom claim 'slurm_username' (set by Keycloak mapper)
2. Static mapping file (globus_uid or email -> slurm user)
3. Username prefix extraction (alice@pnnl.gov -> alice)
4. Fallback to SLURM_SERVICE_USER (default: root)
"""

import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Default mapping file path
IDENTITY_MAP_PATH = os.getenv(
    "SLURM_IDENTITY_MAP", "/app/config/identity_map.json"
)


class IdentityMapper:
    """Maps external identities to Slurm usernames."""

    def __init__(self, mapping_file: Optional[str] = None, fallback_user: str = "root"):
        self._static_map: Dict[str, str] = {}
        self._fallback_user = fallback_user
        self._mapping_file = mapping_file or IDENTITY_MAP_PATH
        self._load_map()

    def _load_map(self):
        """Load static identity mapping from JSON file."""
        if not os.path.exists(self._mapping_file):
            logger.info(
                f"No identity mapping file at {self._mapping_file} — "
                f"using claim-based mapping only"
            )
            return

        try:
            with open(self._mapping_file) as f:
                data = json.load(f)
            self._static_map = data.get("mappings", {})
            logger.info(
                f"Loaded {len(self._static_map)} identity mappings "
                f"from {self._mapping_file}"
            )
        except Exception as e:
            logger.warning(f"Failed to load identity map: {e}")

    def resolve(
        self,
        slurm_username_claim: Optional[str] = None,
        globus_identity: Optional[str] = None,
        preferred_username: Optional[str] = None,
        sub: Optional[str] = None,
    ) -> str:
        """
        Resolve Slurm username from JWT claims.

        Args:
            slurm_username_claim: Direct slurm_username claim from Keycloak JWT
            globus_identity: Globus user UUID (sub from Globus token)
            preferred_username: User's email/username (e.g., alice@pnnl.gov)
            sub: Keycloak user UUID

        Returns:
            Slurm username string
        """
        # Priority 1: Direct slurm_username claim
        if slurm_username_claim:
            logger.debug(f"Using slurm_username claim: {slurm_username_claim}")
            return slurm_username_claim

        # Priority 2: Static mapping by Globus identity
        if globus_identity and globus_identity in self._static_map:
            mapped = self._static_map[globus_identity]
            logger.debug(
                f"Mapped Globus identity {globus_identity} -> {mapped}"
            )
            return mapped

        # Priority 3: Static mapping by email/username
        if preferred_username and preferred_username in self._static_map:
            mapped = self._static_map[preferred_username]
            logger.debug(
                f"Mapped username {preferred_username} -> {mapped}"
            )
            return mapped

        # Priority 4: Static mapping by Keycloak sub
        if sub and sub in self._static_map:
            mapped = self._static_map[sub]
            logger.debug(f"Mapped sub {sub} -> {mapped}")
            return mapped

        # Priority 5: Extract username prefix from email
        if preferred_username and "@" in preferred_username:
            prefix = preferred_username.split("@")[0]
            logger.debug(
                f"Extracted username prefix: {preferred_username} -> {prefix}"
            )
            return prefix

        # Priority 6: Fallback to service user
        logger.debug(f"No identity mapping found, using fallback: {self._fallback_user}")
        return self._fallback_user


# Singleton instance
_mapper: Optional[IdentityMapper] = None


def get_identity_mapper() -> IdentityMapper:
    """Get or create the singleton IdentityMapper."""
    global _mapper
    if _mapper is None:
        from .config import config
        _mapper = IdentityMapper(fallback_user=config.service_user)
    return _mapper
