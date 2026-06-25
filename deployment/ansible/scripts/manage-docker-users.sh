#!/usr/bin/env bash
# manage-docker-users.sh — Post-Docker-install user management for ADEPT VMs
#
# Adds system users to the docker group so they can run Docker commands
# (make targets, validation scripts, docker exec, etc.) without sudo.
#
# This script is intended to run AFTER Docker CE is installed (Phase 3 of
# prepare-rocky-vm.yml) and BEFORE developers begin using the ADEPT stack.
#
# Usage:
#   sudo bash deployment/ansible/scripts/manage-docker-users.sh add <user1> [user2 ...]
#   sudo bash deployment/ansible/scripts/manage-docker-users.sh list
#   sudo bash deployment/ansible/scripts/manage-docker-users.sh verify [user1 ...]
#
# Examples:
#   sudo bash deployment/ansible/scripts/manage-docker-users.sh add dowd665 geor228
#   sudo bash deployment/ansible/scripts/manage-docker-users.sh list
#   sudo bash deployment/ansible/scripts/manage-docker-users.sh verify dowd665 geor228
#
# Prerequisites:
#   - Docker CE installed (docker group exists)
#   - sudo privileges (usermod requires root)
#   - Target users must already exist as system accounts (useradd / LDAP / SSSD)
#
# Post-run:
#   Each added user must activate the group in their own shell:
#     newgrp docker          # Immediate (starts a new shell)
#     # — OR —
#     # Log out and back in   # Most reliable for SSH sessions
#
# Related:
#   - deployment/ansible/playbooks/prepare-rocky-vm.yml (Phase 3: adds adept_user)
#   - docs/SYSTEMS_ADMINISTRATOR_ONBOARDING.md (Docker Group Membership section)
#   - deployment/ansible/README.md (Post-Install User Management section)

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
    cat <<'EOF'
Usage: sudo bash manage-docker-users.sh <command> [args...]

Commands:
  add <user1> [user2 ...]    Add users to the docker group
  list                       List all current docker group members
  verify [user1 ...]         Verify users have docker access (no sudo required)

Examples:
  sudo bash manage-docker-users.sh add dowd665 geor228
  sudo bash manage-docker-users.sh list
  sudo bash manage-docker-users.sh verify dowd665 geor228
EOF
    exit 1
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

preflight() {
    # Docker group must exist
    if ! getent group docker >/dev/null 2>&1; then
        log_error "Docker group does not exist. Is Docker CE installed?"
        log_error "Run the ansible playbook first: prepare-rocky-vm.yml (Phase 3)"
        exit 1
    fi

    # Must be root for add operations
    if [[ "${1:-}" == "add" && $EUID -ne 0 ]]; then
        log_error "The 'add' command requires root privileges. Re-run with sudo."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_add() {
    if [[ $# -eq 0 ]]; then
        log_error "No usernames provided."
        echo "Usage: sudo bash manage-docker-users.sh add <user1> [user2 ...]"
        exit 1
    fi

    local added=0 skipped=0 failed=0

    for user in "$@"; do
        # Check system user exists
        if ! id "$user" >/dev/null 2>&1; then
            log_error "System user '$user' does not exist. Create the account first (useradd / LDAP)."
            ((failed++))
            continue
        fi

        # Check if already in docker group
        if id -nG "$user" 2>/dev/null | grep -qw docker; then
            log_ok "$user — already in docker group"
            ((skipped++))
            continue
        fi

        # Add to docker group
        if usermod -aG docker "$user"; then
            log_ok "$user — added to docker group"
            ((added++))
        else
            log_error "$user — failed to add to docker group"
            ((failed++))
        fi
    done

    echo ""
    echo "Summary: ${added} added, ${skipped} already members, ${failed} failed"

    if [[ $added -gt 0 ]]; then
        echo ""
        log_warn "Each newly added user must activate the group in their own shell:"
        echo "    newgrp docker          # starts a new shell with docker group active"
        echo "    # — or log out and back in (most reliable for SSH sessions)"
        echo ""
        log_info "Verify with: bash $(realpath "$0") verify $*"
    fi
}

cmd_list() {
    local members
    members=$(getent group docker | cut -d: -f4)
    local gid
    gid=$(getent group docker | cut -d: -f3)

    echo "Docker group (GID ${gid}) members:"
    echo ""

    if [[ -z "$members" ]]; then
        log_warn "No users in docker group."
        return
    fi

    # Split comma-separated members
    IFS=',' read -ra users <<< "$members"
    for user in "${users[@]}"; do
        # Check if user has an active session (logged in)
        if who | grep -qw "^${user}"; then
            local active="${GREEN}(active session)${NC}"
        else
            local active=""
        fi
        echo -e "  - ${user} ${active}"
    done

    echo ""
    echo "Total: ${#users[@]} member(s)"
}

cmd_verify() {
    local users_to_check=("$@")

    # If no users specified, check all docker group members
    if [[ ${#users_to_check[@]} -eq 0 ]]; then
        local members
        members=$(getent group docker | cut -d: -f4)
        if [[ -z "$members" ]]; then
            log_warn "No users in docker group. Nothing to verify."
            return
        fi
        IFS=',' read -ra users_to_check <<< "$members"
    fi

    local pass=0 fail=0

    echo "Verifying docker group membership:"
    echo ""

    for user in "${users_to_check[@]}"; do
        if ! id "$user" >/dev/null 2>&1; then
            log_error "$user — system user does not exist"
            ((fail++))
            continue
        fi

        if id -nG "$user" 2>/dev/null | grep -qw docker; then
            local groups
            groups=$(id -nG "$user" 2>/dev/null | tr ' ' ', ')
            log_ok "$user — in docker group (groups: ${groups})"
            ((pass++))
        else
            log_error "$user — NOT in docker group"
            echo "         Fix: sudo usermod -aG docker $user"
            ((fail++))
        fi
    done

    echo ""
    echo "Result: ${pass} verified, ${fail} failed"

    if [[ $fail -gt 0 ]]; then
        echo ""
        log_info "To add missing users: sudo bash $(realpath "$0" 2>/dev/null || echo "manage-docker-users.sh") add <user1> [user2 ...]"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
    usage
fi

command="$1"
shift

preflight "$command"

case "$command" in
    add)    cmd_add "$@" ;;
    list)   cmd_list ;;
    verify) cmd_verify "$@" ;;
    -h|--help|help) usage ;;
    *)
        log_error "Unknown command: $command"
        usage
        ;;
esac
