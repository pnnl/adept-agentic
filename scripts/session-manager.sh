#!/usr/bin/env bash
# Session manager helper for ADEPT developer workflow.
# Handles conversation history backup/archive and optional tmux operations.
# tmux commands are guarded -- they no-op if tmux is not installed.
set -euo pipefail

CLAUDE_PROJECTS_DIR="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
BACKUP_BASE_DIR="${CLAUDE_BACKUP_DIR:-$HOME/.claude/backups}"
LAST_BACKUP_MARKER="$CLAUDE_PROJECTS_DIR/.last-backup"

usage() {
    cat <<EOF
Usage: $(basename "$0") <command> [args]

Commands:
  backup              Back up conversation history (jsonl files newer than last backup)
  archive [title]     Archive + create session index with optional title
  status              Show backup status (last backup time, file counts)
  gh-preflight        Check GitHub authentication and required scopes
  tmux-list           List tmux sessions (no-op if tmux unavailable)
  tmux-create <name>  Create named tmux session (no-op if tmux unavailable)
  tmux-attach <name>  Attach to named tmux session (no-op if tmux unavailable)

Environment:
  CLAUDE_PROJECTS_DIR   Claude projects directory (default: ~/.claude/projects)
  CLAUDE_BACKUP_DIR     Backup destination (default: ~/.claude/backups)
EOF
}

cmd_backup() {
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local dest="$BACKUP_BASE_DIR/$timestamp"

    if [[ ! -d "$CLAUDE_PROJECTS_DIR" ]]; then
        echo "BACKUP: Up to date (no projects directory at $CLAUDE_PROJECTS_DIR)"
        return 0
    fi

    local count
    if [[ -f "$LAST_BACKUP_MARKER" ]]; then
        count=$(find "$CLAUDE_PROJECTS_DIR" -name "*.jsonl" -newer "$LAST_BACKUP_MARKER" 2>/dev/null | wc -l)
    else
        count=$(find "$CLAUDE_PROJECTS_DIR" -name "*.jsonl" 2>/dev/null | wc -l)
    fi

    if [[ "$count" -eq 0 ]]; then
        echo "BACKUP: Up to date (no new conversations since last backup)"
        return 0
    fi

    mkdir -p "$dest"
    if [[ -f "$LAST_BACKUP_MARKER" ]]; then
        find "$CLAUDE_PROJECTS_DIR" -name "*.jsonl" -newer "$LAST_BACKUP_MARKER" -exec cp {} "$dest/" \;
    else
        find "$CLAUDE_PROJECTS_DIR" -name "*.jsonl" -exec cp {} "$dest/" \;
    fi
    touch "$LAST_BACKUP_MARKER"

    echo "BACKUP: $count file(s) archived to $dest"
}

cmd_archive() {
    local title="${1:-}"
    cmd_backup

    local latest_dir
    latest_dir=$(ls -td "$BACKUP_BASE_DIR"/*/ 2>/dev/null | head -1)
    if [[ -z "$latest_dir" ]]; then
        return 0
    fi

    local branch
    branch=$(git branch --show-current 2>/dev/null || echo "unknown")
    local commits
    commits=$(git log --oneline --since="8 hours ago" --author="$(git config user.name 2>/dev/null || echo unknown)" 2>/dev/null | wc -l)

    cat > "$latest_dir/SESSION_INDEX.txt" <<EOF
Session: ${title:-unnamed}
Date: $(date +%Y-%m-%d\ %H:%M)
Branch: $branch
Commits (last 8h): $commits
EOF

    if [[ -n "$title" ]]; then
        echo "ARCHIVE: Session index created with title: $title"
    fi
}

cmd_status() {
    echo "Backup directory: $BACKUP_BASE_DIR"
    if [[ -f "$LAST_BACKUP_MARKER" ]]; then
        echo "Last backup: $(stat -c %y "$LAST_BACKUP_MARKER" 2>/dev/null || stat -f %Sm "$LAST_BACKUP_MARKER" 2>/dev/null)"
    else
        echo "Last backup: never"
    fi
    local total=0
    if [[ -d "$CLAUDE_PROJECTS_DIR" ]]; then
        total=$(find "$CLAUDE_PROJECTS_DIR" -name "*.jsonl" 2>/dev/null | wc -l)
    fi
    echo "Total conversation files: $total"
    local backups=0
    if [[ -d "$BACKUP_BASE_DIR" ]]; then
        backups=$(find "$BACKUP_BASE_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
    fi
    echo "Backup snapshots: $backups"
}

cmd_gh_preflight() {
    if ! command -v gh >/dev/null 2>&1; then
        echo "GITHUB PRE-FLIGHT: FAIL"
        echo "  GitHub CLI (gh) not installed."
        echo "  Install: https://cli.github.com/"
        return 1
    fi

    local auth_output
    auth_output=$(gh auth status 2>&1) || true

    if echo "$auth_output" | grep -q "not logged in"; then
        echo "GITHUB PRE-FLIGHT: FAIL"
        echo "  No GitHub authentication detected."
        echo "  Fix: gh auth login"
        echo "  Or: export GH_TOKEN=<your-pat-with-repo,workflow-scopes>"
        return 1
    fi

    local scopes
    scopes=$(echo "$auth_output" | grep -i "token scopes" | head -1 || echo "")

    local missing=""
    if [[ -n "$scopes" ]]; then
        echo "$scopes" | grep -q "repo" || missing="${missing}repo, "
        echo "$scopes" | grep -q "workflow" || missing="${missing}workflow, "
    fi

    local account
    account=$(echo "$auth_output" | grep -oP "Logged in to .* as \K\S+" | head -1 || echo "unknown")

    if [[ -n "$missing" ]]; then
        missing="${missing%, }"
        echo "GITHUB PRE-FLIGHT: WARNING"
        echo "  Authenticated as: $account"
        echo "  Missing scopes: $missing"
        echo "  Fix: gh auth refresh -s repo,workflow"
        return 0
    fi

    echo "GITHUB PRE-FLIGHT: PASS"
    echo "  Authenticated as: $account"
    if [[ -n "$scopes" ]]; then
        echo "  $scopes"
    fi
}

cmd_tmux_list() {
    if ! command -v tmux >/dev/null 2>&1; then
        echo "TMUX: Not installed (skipping)"
        return 0
    fi
    tmux list-sessions 2>/dev/null || echo "No active tmux sessions"
}

cmd_tmux_create() {
    local name="${1:?Usage: session-manager.sh tmux-create <name>}"
    if ! command -v tmux >/dev/null 2>&1; then
        echo "TMUX: Not installed (skipping)"
        return 0
    fi
    if tmux has-session -t "$name" 2>/dev/null; then
        echo "TMUX: Session '$name' already exists. Attach with: tmux attach -t $name"
    else
        tmux new-session -d -s "$name"
        echo "TMUX: Created session '$name'. Attach with: tmux attach -t $name"
    fi
}

cmd_tmux_attach() {
    local name="${1:?Usage: session-manager.sh tmux-attach <name>}"
    if ! command -v tmux >/dev/null 2>&1; then
        echo "TMUX: Not installed (skipping)"
        return 0
    fi
    if tmux has-session -t "$name" 2>/dev/null; then
        echo "TMUX: Attaching to '$name'..."
        tmux attach -t "$name"
    else
        echo "TMUX: Session '$name' not found. Create with: session-manager.sh tmux-create $name"
        return 1
    fi
}

case "${1:-}" in
    backup)       cmd_backup ;;
    archive)      cmd_archive "${2:-}" ;;
    status)       cmd_status ;;
    gh-preflight) cmd_gh_preflight ;;
    tmux-list)    cmd_tmux_list ;;
    tmux-create)  cmd_tmux_create "${2:-}" ;;
    tmux-attach)  cmd_tmux_attach "${2:-}" ;;
    -h|--help|"") usage ;;
    *)            echo "Unknown command: $1"; usage; exit 1 ;;
esac
