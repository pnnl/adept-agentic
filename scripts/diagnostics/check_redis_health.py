#!/usr/bin/env python3
"""
ADEPT Redis Infrastructure Health Check

Validates that all Redis instances are properly isolated and that the
orchestration service can reach the correct ADEPT core Redis (database /0)
where external tool configurations are stored.

Background (Session 98):
    Sub-stack MCP servers each run their own Redis for session state. If a
    sub-stack defines its Redis service with the generic name "redis" on a
    shared Docker network, Docker DNS shadows the ADEPT core Redis and the
    orchestration service connects to the wrong instance.

Usage:
    python3 scripts/diagnostics/check_redis_health.py             # all checks
    python3 scripts/diagnostics/check_redis_health.py --dns-only  # DNS only
    python3 scripts/diagnostics/check_redis_health.py --tools-only # tools only
    make validate-redis-dns
    make validate-redis-external-tools

Exit codes:
    0 — All checks passed
    1 — DNS shadowing or tool visibility mismatch detected
"""

import subprocess
import sys


def run(cmd: str) -> str:
    """Run a shell command, return stdout (empty on failure)."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def get_container_networks(container_name: str) -> dict:
    """Return {network_name: ip_address} for a container."""
    raw = run(
        f"docker inspect {container_name} "
        f"--format '{{{{range $net, $conf := .NetworkSettings.Networks}}}}"
        f"{{{{$net}}}}={{{{$conf.IPAddress}}}} {{{{end}}}}'"
    )
    result = {}
    for pair in raw.split():
        if "=" in pair:
            net, ip = pair.split("=", 1)
            result[net] = ip
    return result


KNOWN_REDIS = [
    "redis", "emsl_redis", "biofoundation_redis",
    "vfm_redis", "academy_redis", "langfuse-redis",
]


def check_dns() -> bool:
    """Verify orchestration_service resolves 'redis' to ADEPT core Redis."""
    print("=" * 60)
    print("CHECK: Redis DNS Resolution")
    print("=" * 60)

    core_nets = get_container_networks("redis")
    core_data_ip = core_nets.get("adept_data_network", "NOT FOUND")
    print(f"\n  ADEPT core Redis:")
    for net, ip in sorted(core_nets.items()):
        print(f"    {net}: {ip}")

    resolved_ip = run(
        "docker exec orchestration_service python3 -c "
        "\"import socket; print(socket.gethostbyname('redis'))\""
    )
    print(f"\n  orchestration_service resolves 'redis' to: {resolved_ip}")
    print(f"  Expected (adept_data_network):               {core_data_ip}")

    print("\n  All Redis containers:")
    shadowing = []
    for name in KNOWN_REDIS:
        nets = get_container_networks(name)
        if not nets:
            continue
        svc_name = run(
            f"docker inspect {name} --format "
            f"'{{{{index .Config.Labels \"com.docker.compose.service\"}}}}'"
        )
        marker = ""
        if name != "redis" and "adept_application_network" in nets and svc_name == "redis":
            marker = "  ** DNS SHADOW **"
            shadowing.append(name)
        net_str = ", ".join(f"{n}={ip}" for n, ip in sorted(nets.items()))
        print(f"    {name}: {net_str}{marker}")

    print()
    if resolved_ip == core_data_ip:
        print("  PASS: DNS resolves correctly to ADEPT core Redis")
        return True
    elif shadowing:
        print(f"  FAIL: DNS SHADOWED by {shadowing}")
        print(f"  FIX: Rename 'redis' service to a unique name in those compose files.")
        return False
    else:
        print(f"  FAIL: DNS mismatch (got {resolved_ip}, expected {core_data_ip})")
        return False


def check_tools() -> bool:
    """Compare external tools in ADEPT Redis vs what orchestration sees."""
    print("\n" + "=" * 60)
    print("CHECK: External Tool Visibility")
    print("=" * 60)

    raw_keys = run('docker exec redis redis-cli KEYS "external_tool:*"')
    core_tools = sorted(
        k.replace("external_tool:", "")
        for k in raw_keys.split("\n")
        if k.startswith("external_tool:")
    )
    print(f"\n  Tools in ADEPT core Redis: {len(core_tools)}")
    for t in core_tools:
        print(f"    - {t}")

    orch_script = (
        "import asyncio, redis.asyncio as aioredis, os; "
        "async def check(): "
        "    url = os.getenv('REDIS_URL', 'redis://redis:6379/0').rsplit('/', 1)[0] + '/0'; "
        "    r = aioredis.from_url(url, decode_responses=True); "
        "    keys = sorted([k.replace('external_tool:', '') async for k in r.scan_iter('external_tool:*')]); "
        "    print(chr(10).join(keys)); "
        "    await r.aclose(); "
        "asyncio.run(check())"
    )
    orch_output = run(f'docker exec orchestration_service python3 -c "{orch_script}"')
    orch_tools = sorted(t for t in orch_output.split("\n") if t.strip())
    print(f"\n  Tools visible to orchestration: {len(orch_tools)}")
    for t in orch_tools:
        print(f"    - {t}")

    missing = set(core_tools) - set(orch_tools)
    print()
    if not missing and len(core_tools) == len(orch_tools):
        print(f"  PASS: All {len(core_tools)} tools visible")
        return True
    else:
        if missing:
            print(f"  FAIL: {len(missing)} tools INVISIBLE to orchestration:")
            for t in sorted(missing):
                print(f"    - {t}")
        print("\n  Run 'make validate-redis-dns' to diagnose.")
        return False


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--all"
    print("ADEPT Redis Infrastructure Health Check\n")

    dns_ok = tools_ok = True
    if mode in ("--all", "--dns-only"):
        dns_ok = check_dns()
    if mode in ("--all", "--tools-only"):
        tools_ok = check_tools()

    print("\n" + "=" * 60)
    if mode != "--dns-only":
        print(f"  Tool Visibility: {'PASS' if tools_ok else 'FAIL'}")
    if mode != "--tools-only":
        print(f"  Redis DNS:       {'PASS' if dns_ok else 'FAIL'}")

    sys.exit(0 if (dns_ok and tools_ok) else 1)


if __name__ == "__main__":
    main()
