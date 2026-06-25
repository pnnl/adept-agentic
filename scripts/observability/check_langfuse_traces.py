#!/usr/bin/env python3
"""Quick script to check all traces in Langfuse"""
import httpx
import base64
import json

LANGFUSE_HOST = "http://langfuse-web:3000"
PUBLIC_KEY = "pk-lf-abf5b717-80ac-41bb-bac1-c835070c270c"
SECRET_KEY = "sk-lf-4fe225a7-386a-457d-8aa6-7ef9c2eb83e7"

auth_string = base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()
headers = {"Authorization": f"Basic {auth_string}"}

client = httpx.Client()
response = client.get(f"{LANGFUSE_HOST}/api/public/traces", headers=headers, params={"limit": 20})
data = response.json()

print(f"Status: {response.status_code}")
print(f"Total traces found: {len(data.get('data', []))}")
print(f"\nRecent traces:")
for trace in data.get("data", [])[:10]:
    print(f"  - ID: {trace.get('id')[:16]}..., SessionID: {trace.get('sessionId')}, Name: {trace.get('name')}, Timestamp: {trace.get('timestamp')}")

# Try searching by recent session IDs
recent_session_ids = [f"test-pattern-{i}-" for i in range(1, 4)]
print(f"\nSearching for test patterns...")
for pattern_prefix in recent_session_ids:
    matches = [t for t in data.get("data", []) if t.get('sessionId', '').startswith(pattern_prefix)]
    print(f"  {pattern_prefix}: {len(matches)} matches")
