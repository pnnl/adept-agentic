#!/bin/bash
# Entrypoint script for sandbox_mcp_server
# Handles runtime permissions for shared volumes and session directories
# Supports multi-tier session isolation for secure code execution

set -e

# Function to set up session directory hierarchy
setup_session_hierarchy() {
    local base_path="$1"

    echo "🔧 Setting up session hierarchy at $base_path..."

    # Create necessary subdirectories
    mkdir -p "$base_path/sessions"
    mkdir -p "$base_path/plots"

    # Set proper ownership and permissions
    chown -R appuser:appgroup "$base_path"
    chmod -R 755 "$base_path"

    # Group-writable: base dir and plots (exec user GID=appgroup needs write access)
    chmod 775 "$base_path"
    chmod 775 "$base_path/plots"
    # World-writable: sessions dir (any UID can create session subdirs)
    chmod 777 "$base_path/sessions"

    echo "✅ Session hierarchy configured at $base_path"
}

# Create SANDBOX_EXEC_USER passwd entry if configured (for Gurobi token server auth)
# The token server validates the connecting process's OS username (whoami), not env vars.
# This creates the user so getpwuid() and whoami resolve correctly when subprocess
# switches UID via os.setuid() or nsjail uidmap.
if [ -n "${SANDBOX_EXEC_USER:-}" ]; then
    EXEC_UID="${SANDBOX_EXEC_UID:-1500}"
    # GID defaults to appgroup (1200) so exec user can write to shared volume
    EXEC_GID="${SANDBOX_EXEC_GID:-1200}"
    if ! getent passwd "$SANDBOX_EXEC_USER" &>/dev/null; then
        echo "Creating sandbox exec user: $SANDBOX_EXEC_USER (UID=$EXEC_UID, GID=$EXEC_GID/appgroup)"
        useradd -u "$EXEC_UID" -g "$EXEC_GID" -M -d /tmp -s /bin/false "$SANDBOX_EXEC_USER" 2>/dev/null || \
            echo "${SANDBOX_EXEC_USER}:x:${EXEC_UID}:${EXEC_GID}:Sandbox Exec User:/tmp:/bin/false" >> /etc/passwd
    fi
fi

# Fix permissions on shared volume at runtime
# This ensures the appuser can write to the mounted shared volume
if [ -d "/app/data/uploaded_files" ]; then
    echo "🔧 Fixing runtime permissions for shared volume..."
    setup_session_hierarchy "/app/data/uploaded_files"
fi

# Set up tmpfs session directory if available (hybrid approach)
if [ -d "/tmp/sandbox_sessions" ]; then
    echo "🔧 Setting up tmpfs session directory..."
    setup_session_hierarchy "/tmp/sandbox_sessions"
fi

# Debug: Show user context and directory permissions
echo "📊 Debug: Current user context"
echo "   - UID: $(id -u)"
echo "   - GID: $(id -g)"
echo "   - Groups: $(id -G)"

if [ -d "/app/data/uploaded_files" ]; then
    echo "📊 Debug: Shared volume permissions"
    ls -la /app/data/uploaded_files/ | head -5
fi

if [ -d "/tmp/sandbox_sessions" ]; then
    echo "📊 Debug: tmpfs permissions"
    ls -la /tmp/sandbox_sessions/ | head -5
fi

# Apply egress allowlist (nftables rules) — fail-closed on error
if [ "${SANDBOX_EGRESS_RESTRICTION_ENABLED:-true}" = "true" ]; then
    echo "Applying sandbox egress allowlist..."
    /app/.venv/bin/python -c "
from agentic_framework_pkg.sandbox_mcp_server.security.egress_allowlist import load_and_validate
from agentic_framework_pkg.sandbox_mcp_server.security.egress_firewall import apply_egress_rules
from pathlib import Path

config_path = Path('/app/config/sandbox_egress_allowlist.yaml')
allowlist = load_and_validate(config_path)
success = apply_egress_rules(allowlist)
if success:
    print(f'  Egress allowlist: {len(allowlist.rules)} rules applied')
else:
    if not allowlist.rules:
        print('  Egress allowlist: no config present — all external egress denied (secure default)')
    else:
        print('  WARNING: nftables apply failed — default DROP policy active (fail-closed)')
" 2>&1
    echo "Egress policy applied"
else
    echo "WARNING: SANDBOX_EGRESS_RESTRICTION_ENABLED=false — egress unrestricted (development mode)"
fi

# Validate Gurobi license file accessibility (opt-in)
if [ -n "${GRB_LICENSE_FILE:-}" ]; then
    if [ -f "$GRB_LICENSE_FILE" ]; then
        echo "Gurobi license file found at $GRB_LICENSE_FILE ($(wc -c < "$GRB_LICENSE_FILE") bytes)"
    else
        echo "GRB_LICENSE_FILE=$GRB_LICENSE_FILE set but file not found (Gurobi disabled)"
    fi
fi

# Privilege handling: nsjail requires root to create namespaces and set securebits.
# When nsjail is active, the service keeps root and nsjail itself drops privileges
# inside the jail (uidmap to 65534/nobody). This is strictly superior isolation to
# gosu-based UID separation because jailed code has: no capabilities, restricted
# syscalls, separate PID/mount/IPC/UTS namespaces, and a minimal filesystem view.
#
# When SANDBOX_EXEC_USER is set, service also stays root so _set_resource_limits()
# can call os.setuid() to switch subprocess identity (Gurobi token server auth).
if [ "${SANDBOX_USE_NSJAIL:-auto}" != "false" ] && [ -x /usr/local/bin/nsjail ]; then
    echo "Starting sandbox_mcp_server as root (nsjail handles privilege isolation)..."
    exec "$@"
elif [ -n "${SANDBOX_EXEC_USER:-}" ]; then
    echo "Starting sandbox_mcp_server as root (subprocess setuid to $SANDBOX_EXEC_USER)..."
    exec "$@"
else
    echo "Starting sandbox_mcp_server as appuser (nsjail disabled)..."
    exec gosu appuser "$@"
fi