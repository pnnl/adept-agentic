#!/bin/bash
# This script is executed when the PostgreSQL container starts for the first time.
# It creates multiple databases required by the Agentic Framework services.
set -e

# Function to create a database if it doesn't exist
create_database() {
    local db_name=$1
    echo "  Creating database '$db_name'"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" -tc "SELECT 1 FROM pg_database WHERE datname = '$db_name'" | grep -q 1 || psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" -c "CREATE DATABASE $db_name"
}

# Create all required databases
create_database "agentic_orchestrator"
create_database "agentic_registry"

echo "All databases created successfully."

