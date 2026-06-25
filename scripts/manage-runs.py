#!/usr/bin/env python3
"""
Wrapper script for the orchestration service run management CLI.

This makes it easy to run the tool from the scripts directory without
having to remember the full module path.
"""
import sys
import subprocess

if __name__ == "__main__":
    # Pass all arguments to the actual CLI module
    cmd = [
        sys.executable, "-m", 
        "agentic_framework_pkg.orchestration_service.cli.manage_runs"
    ] + sys.argv[1:]
    
    sys.exit(subprocess.call(cmd))