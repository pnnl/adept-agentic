"""
Sandbox egress firewall — nftables rule generation and application.

Resolves FQDN hosts to IPs at apply-time, generates nftables ruleset,
and applies it. Fail-closed: if application fails, default policy is DROP.
"""

import logging
import socket
import subprocess

from .egress_allowlist import SandboxEgressAllowlist

logger = logging.getLogger(__name__)

NFTABLES_TEMPLATE = """\
table inet sandbox_egress {{
  chain output {{
    type filter hook output priority 0; policy drop;

    # Allow loopback (container-internal communication)
    oifname "lo" accept

    # Allow established/related (responses to inbound MCP requests)
    ct state established,related accept

    # Allow DNS resolution (required for FQDN rules to work at runtime)
    udp dport 53 accept
    tcp dport 53 accept

    # Allow internal Docker networks (sandbox_net + integration_network only via #104 isolation)
    # NOTE: RFC 1918 ranges still accepted — network isolation via Docker network topology
    # prevents DNS resolution of services on other networks (keycloak, agent_gateway, etc.)
    ip daddr 172.16.0.0/12 accept
    ip daddr 10.0.0.0/8 accept
    ip daddr 192.168.0.0/16 accept

    # Allowlist rules (operator-configured)
{rules}

    # Default deny — log for observability then drop
    counter log prefix "SANDBOX_EGRESS_DENIED: " drop
  }}
}}
"""


def resolve_host(host: str, timeout: float = 5.0) -> list[str]:
    """Resolve hostname to IPv4 addresses. Returns empty list on failure (fail-closed)."""
    original_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        results = socket.getaddrinfo(host, None, socket.AF_INET)
        ips = list(set(r[4][0] for r in results))
        logger.debug("DNS resolved %s -> %s", host, ips)
        return ips
    except (socket.gaierror, socket.timeout, OSError) as e:
        logger.warning(
            "SECURITY: DNS resolution failed for %s: %s — rule skipped (fail-closed)",
            host,
            e,
        )
        return []
    finally:
        socket.setdefaulttimeout(original_timeout)


def generate_ruleset(allowlist: SandboxEgressAllowlist) -> str:
    """Generate nftables ruleset string from validated allowlist."""
    rule_lines = []

    for rule in allowlist.rules:
        ips = resolve_host(rule.host)
        if not ips:
            continue

        safe_comment = rule.comment.replace("\n", " ").replace("\r", " ").replace('"', "'")
        for ip in ips:
            if rule.port is None:
                line = f'    ip daddr {ip} meta l4proto {rule.protocol} accept  # {safe_comment}'
            else:
                line = f'    ip daddr {ip} {rule.protocol} dport {rule.port} accept  # {safe_comment}'
            rule_lines.append(line)

    if rule_lines:
        rules_block = "\n".join(rule_lines)
    else:
        rules_block = "    # No allowlist rules resolved — all external egress denied"

    return NFTABLES_TEMPLATE.format(rules=rules_block)


DENY_ALL_RULESET = """\
table inet sandbox_egress {
  chain output {
    type filter hook output priority 0; policy drop;
    oifname "lo" accept
    ct state established,related accept
    udp dport 53 accept
    tcp dport 53 accept
    ip daddr 172.16.0.0/12 accept
    ip daddr 10.0.0.0/8 accept
    ip daddr 192.168.0.0/16 accept
    counter log prefix "SANDBOX_EGRESS_DENIED: " drop
  }
}
"""


def _apply_deny_all_fallback() -> None:
    """Best-effort: apply a minimal deny-all ruleset after a failed update."""
    try:
        subprocess.run(
            ["nft", "-f", "-"],
            input=DENY_ALL_RULESET.encode(),
            capture_output=True,
            timeout=5,
        )
        logger.warning("SECURITY: Fallback deny-all ruleset applied after update failure")
    except Exception as e:
        logger.error("SECURITY: Fallback deny-all also failed: %s — container may be unfiltered", e)


def apply_egress_rules(allowlist: SandboxEgressAllowlist) -> bool:
    """Apply nftables egress rules. Returns True on success.

    Fail-closed: if application fails after deleting the old table, a minimal
    deny-all ruleset is re-applied as fallback. If nft binary is entirely
    missing, no kernel-level filtering is active (container relies on Docker
    network isolation only).
    """
    ruleset = generate_ruleset(allowlist)

    try:
        subprocess.run(
            ["nft", "delete", "table", "inet", "sandbox_egress"],
            capture_output=True,
            timeout=5,
        )

        result = subprocess.run(
            ["nft", "-f", "-"],
            input=ruleset.encode(),
            capture_output=True,
            timeout=5,
        )

        if result.returncode != 0:
            logger.error(
                "SECURITY: nftables apply failed (rc=%d): %s",
                result.returncode,
                result.stderr.decode().strip(),
            )
            _apply_deny_all_fallback()
            return False

        resolved_count = sum(1 for line in ruleset.splitlines() if "ip daddr" in line and "accept" in line and "172.16" not in line and "10.0.0" not in line and "192.168" not in line)
        logger.info(
            "SECURITY: Egress allowlist applied — %d rules configured, %d IPs resolved",
            len(allowlist.rules),
            resolved_count,
        )
        return True

    except FileNotFoundError:
        logger.error(
            "SECURITY: nft binary not found — install nftables package. "
            "No kernel-level egress filtering active (container relies on Docker network isolation)."
        )
        return False
    except subprocess.TimeoutExpired:
        logger.error("SECURITY: nftables command timed out — applying deny-all fallback")
        _apply_deny_all_fallback()
        return False
    except Exception as e:
        logger.error("SECURITY: nftables application failed: %s — applying deny-all fallback", e)
        _apply_deny_all_fallback()
        return False
