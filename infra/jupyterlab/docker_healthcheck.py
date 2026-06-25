#!/usr/bin/env python3
# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.
#
# MODIFIED: Use /api/status endpoint instead of /api to avoid token generation
# Issue: Health check was generating new tokens every 5 seconds (17,280/day)
# Solution: /api/status endpoint doesn't require auth and doesn't generate tokens
# Reference: docs/troubleshooting/SESSION_36_PORT_FORWARDING_ISSUES_ANALYSIS.md

import json
import os
from pathlib import Path

import requests

# A number of operations below deliberately don't check for possible errors
# As this is a healthcheck, it should succeed or raise an exception on error

runtime_dir = Path("/home/") / os.environ["NB_USER"] / ".local/share/jupyter/runtime/"
json_file = next(runtime_dir.glob("*server-*.json"))

url = json.loads(json_file.read_bytes())["url"]
# CRITICAL FIX: Use /api/status instead of /api
# /api/status does NOT require authentication and does NOT generate tokens
url = url + "api/status"

proxies = {
    "http": "",
    "https": "",
}

r = requests.get(url, proxies=proxies, verify=False)  # request without SSL verification
r.raise_for_status()
print(r.content)
