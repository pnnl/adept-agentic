#!/bin/bash
# scripts/deps/sync_env_example_to_env.sh
# Syncs new variables from .env.example to .env without overwriting existing values
# Useful after pulling changes that add new environment variables

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ENV_FILE=".env"
EXAMPLE_FILE=".env.example"

# Check if .env.example exists
if [ ! -f "$EXAMPLE_FILE" ]; then
  echo -e "${RED}ERROR: $EXAMPLE_FILE not found${NC}"
  exit 1
fi

# Check if .env exists
if [ ! -f "$ENV_FILE" ]; then
  echo -e "${YELLOW}INFO: $ENV_FILE not found, creating from $EXAMPLE_FILE${NC}"
  cp "$EXAMPLE_FILE" "$ENV_FILE"
  echo -e "${GREEN}✅ Created $ENV_FILE from $EXAMPLE_FILE${NC}"
  exit 0
fi

echo -e "${YELLOW}==> Syncing new variables from $EXAMPLE_FILE to $ENV_FILE...${NC}"

# Extract variable names from .env.example (ignoring comments and empty lines)
EXAMPLE_VARS=$(grep -E '^[A-Z_]+=.*' "$EXAMPLE_FILE" | cut -d '=' -f 1 | sort -u)

# Track changes
ADDED_COUNT=0
SKIPPED_COUNT=0

# Create backup
BACKUP_FILE="${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$ENV_FILE" "$BACKUP_FILE"
echo -e "   Backup created: $BACKUP_FILE"

# Process each variable from .env.example
while IFS= read -r VAR_NAME; do
  # Check if variable already exists in .env
  if grep -q "^${VAR_NAME}=" "$ENV_FILE"; then
    SKIPPED_COUNT=$((SKIPPED_COUNT + 1))
  else
    # Variable doesn't exist, add it from .env.example
    echo -e "${YELLOW}   Adding: $VAR_NAME${NC}"

    # Extract the full line from .env.example (with comments if any)
    # Find the line and any preceding comment lines
    LINE_NUM=$(grep -n "^${VAR_NAME}=" "$EXAMPLE_FILE" | cut -d: -f1)

    if [ -n "$LINE_NUM" ]; then
      # Look for comment lines immediately before this variable
      COMMENT_START=$LINE_NUM
      while [ $COMMENT_START -gt 1 ]; do
        PREV_LINE=$(sed -n "$((COMMENT_START - 1))p" "$EXAMPLE_FILE")
        if [[ "$PREV_LINE" =~ ^#.*$ ]] || [ -z "$PREV_LINE" ]; then
          COMMENT_START=$((COMMENT_START - 1))
        else
          break
        fi
      done

      # Add a newline separator before the new variable block
      echo "" >> "$ENV_FILE"

      # Copy comment lines and the variable line
      if [ $COMMENT_START -lt $LINE_NUM ]; then
        sed -n "${COMMENT_START},${LINE_NUM}p" "$EXAMPLE_FILE" >> "$ENV_FILE"
      else
        sed -n "${LINE_NUM}p" "$EXAMPLE_FILE" >> "$ENV_FILE"
      fi

      ADDED_COUNT=$((ADDED_COUNT + 1))
    fi
  fi
done <<< "$EXAMPLE_VARS"

echo ""
echo -e "${GREEN}✅ Sync complete:${NC}"
echo -e "   Added: $ADDED_COUNT new variables"
echo -e "   Skipped: $SKIPPED_COUNT existing variables (preserved)"
echo -e "   Backup: $BACKUP_FILE"

if [ $ADDED_COUNT -gt 0 ]; then
  echo ""
  echo -e "${YELLOW}⚠️  Important:${NC}"
  echo -e "   Review new variables in $ENV_FILE and set appropriate values"
  echo -e "   Run 'git diff --no-index $BACKUP_FILE $ENV_FILE' to see changes"
fi
