"""
JWT Bridge Unit Tests
=====================

Tests for the SPIFFE JWT-SVID -> Slurm HS256 JWT translation bridge.
Runs offline — no SPIRE agent or slurmrestd required.
"""

import base64
import time

import pytest

try:
    import jwt as pyjwt
except ImportError:
    pytest.skip("PyJWT not installed", allow_module_level=True)

from slurm_mcp.jwt_bridge import JWTBridge, JWTBridgeError, get_jwt_bridge


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A deterministic HMAC key for testing
TEST_HMAC_KEY = base64.b64encode(b"test-slurm-hmac-key-32-bytes!!!!").decode()

# Build a fake SPIFFE JWT-SVID (RS256 structure, but we skip signature verification)
def _make_spiffe_jwt(
    sub="spiffe://pnnl.adept.slurm/slurm-mcp-server",
    aud="slurmrestd",
    exp_offset=3600,
):
    """Create a fake SPIFFE JWT-SVID for testing (unsigned — bridge decodes without verification)."""
    now = int(time.time())
    payload = {
        "sub": sub,
        "aud": [aud] if isinstance(aud, str) else aud,
        "iat": now,
        "exp": now + exp_offset,
    }
    # Encode with HS256 for simplicity — bridge decodes without verification
    return pyjwt.encode(payload, "fake-key", algorithm="HS256")


@pytest.fixture
def bridge():
    """Create a JWTBridge with test HMAC key."""
    return JWTBridge(
        hmac_key_b64=TEST_HMAC_KEY,
        default_username="root",
        token_ttl=3600,
    )


@pytest.fixture
def bridge_no_key():
    """Create a JWTBridge without HMAC key."""
    return JWTBridge(hmac_key_b64="", default_username="root")


# ---------------------------------------------------------------------------
# Test: Initialization
# ---------------------------------------------------------------------------

class TestJWTBridgeInit:
    def test_init_with_hmac_key(self, bridge):
        assert bridge.has_hmac_key is True

    def test_init_without_hmac_key(self, bridge_no_key):
        assert bridge_no_key.has_hmac_key is False

    def test_default_trust_domains(self, bridge):
        assert "pnnl.adept.slurm" in bridge._trust_domains
        assert "pnnl.adept" in bridge._trust_domains

    def test_custom_trust_domains(self):
        b = JWTBridge(
            hmac_key_b64=TEST_HMAC_KEY,
            trust_domains={"custom.domain"},
        )
        assert "custom.domain" in b._trust_domains
        assert "pnnl.adept.slurm" not in b._trust_domains


# ---------------------------------------------------------------------------
# Test: SPIFFE JWT Decoding
# ---------------------------------------------------------------------------

class TestDecodeSpiffeJWT:
    def test_decode_valid_spiffe_jwt(self, bridge):
        token = _make_spiffe_jwt()
        claims = bridge.decode_spiffe_jwt(token)
        assert claims["sub"] == "spiffe://pnnl.adept.slurm/slurm-mcp-server"

    def test_decode_adept_domain(self, bridge):
        token = _make_spiffe_jwt(sub="spiffe://pnnl.adept/orchestration-service")
        claims = bridge.decode_spiffe_jwt(token)
        assert claims["sub"] == "spiffe://pnnl.adept/orchestration-service"

    def test_reject_non_spiffe_sub(self, bridge):
        """Tokens without spiffe:// sub claim are rejected."""
        now = int(time.time())
        token = pyjwt.encode(
            {"sub": "user@example.com", "iat": now, "exp": now + 3600},
            "fake-key",
            algorithm="HS256",
        )
        with pytest.raises(JWTBridgeError, match="must start with 'spiffe://'"):
            bridge.decode_spiffe_jwt(token)

    def test_reject_untrusted_domain(self, bridge):
        """Tokens from untrusted trust domains are rejected."""
        token = _make_spiffe_jwt(sub="spiffe://evil.attacker/malware")
        with pytest.raises(JWTBridgeError, match="Untrusted SPIFFE domain"):
            bridge.decode_spiffe_jwt(token)

    def test_reject_malformed_token(self, bridge):
        """Completely invalid tokens raise JWTBridgeError."""
        with pytest.raises(JWTBridgeError, match="Failed to decode"):
            bridge.decode_spiffe_jwt("not-a-jwt-at-all")

    def test_validate_spiffe_mode_not_implemented(self):
        """Full RS256 validation is not yet implemented."""
        b = JWTBridge(
            hmac_key_b64=TEST_HMAC_KEY,
            validate_spiffe=True,
        )
        token = _make_spiffe_jwt()
        with pytest.raises(JWTBridgeError, match="not yet implemented"):
            b.decode_spiffe_jwt(token)


# ---------------------------------------------------------------------------
# Test: SPIFFE ID -> Slurm Username Mapping
# ---------------------------------------------------------------------------

class TestSpiffeToUsernameMapping:
    def test_map_workload_name_from_path(self, bridge):
        """SPIFFE path last segment maps to username."""
        username = bridge._map_spiffe_to_username(
            "spiffe://pnnl.adept.slurm/slurm-mcp-server"
        )
        assert username == "slurm-mcp-server"

    def test_map_adept_orchestration(self, bridge):
        username = bridge._map_spiffe_to_username(
            "spiffe://pnnl.adept/orchestration-service"
        )
        assert username == "orchestration-service"

    def test_map_nested_path(self, bridge):
        username = bridge._map_spiffe_to_username(
            "spiffe://pnnl.adept/namespace/worker-1"
        )
        assert username == "worker-1"

    def test_map_fallback_to_default(self, bridge):
        """Short SPIFFE IDs fall back to default username."""
        username = bridge._map_spiffe_to_username("spiffe://pnnl.adept")
        assert username == "root"


# ---------------------------------------------------------------------------
# Test: Slurm HS256 Token Generation
# ---------------------------------------------------------------------------

class TestSlurmTokenGeneration:
    def test_generate_valid_hs256_token(self, bridge):
        token = bridge._generate_slurm_token("testuser")
        key_bytes = base64.b64decode(TEST_HMAC_KEY)
        claims = pyjwt.decode(token, key_bytes, algorithms=["HS256"])
        assert claims["sun"] == "testuser"
        assert "iat" in claims
        assert "exp" in claims

    def test_token_ttl(self, bridge):
        token = bridge._generate_slurm_token("testuser")
        key_bytes = base64.b64decode(TEST_HMAC_KEY)
        claims = pyjwt.decode(token, key_bytes, algorithms=["HS256"])
        assert claims["exp"] - claims["iat"] == 3600

    def test_custom_ttl(self):
        b = JWTBridge(hmac_key_b64=TEST_HMAC_KEY, token_ttl=300)
        token = b._generate_slurm_token("testuser")
        key_bytes = base64.b64decode(TEST_HMAC_KEY)
        claims = pyjwt.decode(token, key_bytes, algorithms=["HS256"])
        assert claims["exp"] - claims["iat"] == 300

    def test_token_caching(self, bridge):
        """Tokens for the same user are cached."""
        t1 = bridge._generate_slurm_token("testuser")
        t2 = bridge._generate_slurm_token("testuser")
        assert t1 == t2  # Same cached token

    def test_different_users_not_cached(self, bridge):
        """Different usernames produce different tokens."""
        t1 = bridge._generate_slurm_token("user1")
        t2 = bridge._generate_slurm_token("user2")
        assert t1 != t2

    def test_no_hmac_key_raises(self, bridge_no_key):
        with pytest.raises(JWTBridgeError, match="No HMAC key"):
            bridge_no_key._generate_slurm_token("testuser")


# ---------------------------------------------------------------------------
# Test: Full Translation Pipeline
# ---------------------------------------------------------------------------

class TestTranslate:
    def test_full_translation(self, bridge):
        """SPIFFE JWT-SVID translates to valid Slurm HS256 JWT."""
        spiffe_token = _make_spiffe_jwt()
        slurm_token = bridge.translate(spiffe_token)

        # Verify the output is a valid Slurm HS256 JWT
        key_bytes = base64.b64decode(TEST_HMAC_KEY)
        claims = pyjwt.decode(slurm_token, key_bytes, algorithms=["HS256"])
        assert "sun" in claims
        assert "iat" in claims
        assert "exp" in claims

    def test_translation_with_username_override(self, bridge):
        """Username override takes precedence over SPIFFE ID mapping."""
        spiffe_token = _make_spiffe_jwt()
        slurm_token = bridge.translate(spiffe_token, username_override="admin")

        key_bytes = base64.b64decode(TEST_HMAC_KEY)
        claims = pyjwt.decode(slurm_token, key_bytes, algorithms=["HS256"])
        assert claims["sun"] == "admin"

    def test_translation_maps_spiffe_id(self, bridge):
        """Without override, username comes from SPIFFE ID path."""
        spiffe_token = _make_spiffe_jwt(
            sub="spiffe://pnnl.adept.slurm/slurmrestd"
        )
        slurm_token = bridge.translate(spiffe_token)

        key_bytes = base64.b64decode(TEST_HMAC_KEY)
        claims = pyjwt.decode(slurm_token, key_bytes, algorithms=["HS256"])
        assert claims["sun"] == "slurmrestd"

    def test_translation_rejects_untrusted_domain(self, bridge):
        """Translation fails for untrusted SPIFFE domains."""
        spiffe_token = _make_spiffe_jwt(sub="spiffe://evil.domain/workload")
        with pytest.raises(JWTBridgeError, match="Untrusted SPIFFE domain"):
            bridge.translate(spiffe_token)


# ---------------------------------------------------------------------------
# Test: Translate-or-Passthrough
# ---------------------------------------------------------------------------

class TestTranslateOrPassthrough:
    def test_passthrough_existing_slurm_token(self, bridge):
        """Tokens with 'sun' claim pass through unchanged."""
        key_bytes = base64.b64decode(TEST_HMAC_KEY)
        now = int(time.time())
        existing_token = pyjwt.encode(
            {"sun": "admin", "iat": now, "exp": now + 3600},
            key_bytes,
            algorithm="HS256",
        )
        result = bridge.translate_or_passthrough(existing_token)
        assert result == existing_token

    def test_translate_spiffe_token(self, bridge):
        """SPIFFE tokens get translated."""
        spiffe_token = _make_spiffe_jwt()
        result = bridge.translate_or_passthrough(spiffe_token)
        # Result should be a different token (HS256 with sun claim)
        key_bytes = base64.b64decode(TEST_HMAC_KEY)
        claims = pyjwt.decode(result, key_bytes, algorithms=["HS256"])
        assert "sun" in claims

    def test_passthrough_garbage_token(self, bridge):
        """Non-JWT strings pass through unchanged."""
        result = bridge.translate_or_passthrough("not-a-jwt")
        assert result == "not-a-jwt"

    def test_passthrough_unknown_format(self, bridge):
        """JWTs without SPIFFE sub or Slurm sun pass through."""
        now = int(time.time())
        token = pyjwt.encode(
            {"user": "someone", "iat": now, "exp": now + 3600},
            "key",
            algorithm="HS256",
        )
        result = bridge.translate_or_passthrough(token)
        assert result == token


# ---------------------------------------------------------------------------
# Test: Factory Function
# ---------------------------------------------------------------------------

class TestGetJWTBridge:
    def test_returns_none_without_env(self, monkeypatch):
        monkeypatch.delenv("SLURM_JWT_KEY", raising=False)
        assert get_jwt_bridge() is None

    def test_returns_bridge_with_env(self, monkeypatch):
        monkeypatch.setenv("SLURM_JWT_KEY", TEST_HMAC_KEY)
        monkeypatch.setenv("SLURM_SERVICE_USER", "testuser")
        bridge = get_jwt_bridge()
        assert bridge is not None
        assert bridge.has_hmac_key is True
        assert bridge._default_username == "testuser"

    def test_custom_ttl_from_env(self, monkeypatch):
        monkeypatch.setenv("SLURM_JWT_KEY", TEST_HMAC_KEY)
        monkeypatch.setenv("SLURM_JWT_BRIDGE_TTL", "600")
        bridge = get_jwt_bridge()
        assert bridge._token_ttl == 600
