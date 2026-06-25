#!/bin/sh
set -e

# This script is executed as root at container startup.

# Create the sessions directory if it doesn't exist.
mkdir -p /app/data/uploaded_files/sessions

# Set the ownership of the shared uploads directory to the appuser.
# This ensures the application has the necessary permissions at runtime.
chown -R appuser:appgroup /app/data/uploaded_files

# Drop privileges and execute the main command (CMD) as the appuser.
exec gosu appuser "$@"
