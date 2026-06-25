#!/usr/bin/env python3

import json
import os
import requests
import httpx


def _get_user_token() -> str:
    """Get Keycloak user token for script authentication."""
    keycloak_url = os.getenv("KEYCLOAK_URL", "http://keycloak:8180")
    realm = os.getenv("KEYCLOAK_REALM", "master")
    token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"
    payload = {
        "client_id": "login-client",
        "username": os.getenv("TEST_USERNAME", "notebook-user"),
        "password": os.getenv("TEST_PASSWORD", "notebook-password"),
        "grant_type": "password",
    }
    response = requests.post(token_url, data=payload)
    response.raise_for_status()
    return response.json()["access_token"]


def _get_authenticated_client() -> httpx.Client:
    """Create an authenticated httpx client for the Agent Gateway."""
    token = _get_user_token()
    base_url = os.getenv("AGENT_GATEWAY_URL", "http://agent_gateway:8081/v1")
    return httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )


def debug_latest_run():
    """Debug the latest run messages to see what happened during execution."""

    try:
        client = _get_authenticated_client()
        
        # Get the latest thread
        print("🔍 Getting latest thread...")
        threads_response = client.get('/v1/threads')
        if threads_response.status_code != 200:
            print(f"❌ Failed to get threads: {threads_response.status_code}")
            return
            
        threads = threads_response.json()['data']
        if not threads:
            print("❌ No threads found")
            return
            
        latest_thread_id = threads[0]['id']
        print(f"✅ Latest thread: {latest_thread_id}")
        
        # Get the latest run
        runs_response = client.get(f'/v1/threads/{latest_thread_id}/runs')
        if runs_response.status_code != 200:
            print(f"❌ Failed to get runs: {runs_response.status_code}")
            return
            
        runs = runs_response.json()['data']
        if not runs:
            print("❌ No runs found")
            return
            
        latest_run_id = runs[0]['id']
        print(f"✅ Latest run: {latest_run_id} (status: {runs[0]['status']})")
        
        # Get all messages in the thread
        messages_response = client.get(f'/v1/threads/{latest_thread_id}/messages')
        if messages_response.status_code != 200:
            print(f"❌ Failed to get messages: {messages_response.status_code}")
            return
            
        messages = messages_response.json()['data']
        print(f"✅ Found {len(messages)} messages")
        
        # Show the last few messages, especially looking for tool_call results
        for i, msg in enumerate(messages[-5:]):  # Show last 5 messages
            print(f"\n📝 Message {i+1}:")
            print(f"   Role: {msg['role']}")
            print(f"   Created: {msg.get('created_at', 'N/A')}")
            
            content = msg.get('content', [])
            if content:
                for j, c in enumerate(content):
                    if c.get('type') == 'text':
                        text_value = c.get('text', {}).get('value', '')
                        print(f"   Content {j+1}: {text_value}")
                    else:
                        print(f"   Content {j+1} ({c.get('type', 'unknown')}): {json.dumps(c, indent=2)}")
            
            # Check for tool calls
            tool_calls = msg.get('tool_calls', [])
            if tool_calls:
                print(f"   🔧 Tool calls: {len(tool_calls)}")
                for k, tc in enumerate(tool_calls):
                    print(f"      Tool {k+1}: {tc.get('function', {}).get('name', 'unknown')}")
                    if tc.get('function', {}).get('arguments'):
                        args = json.loads(tc.get('function', {}).get('arguments', '{}'))
                        print(f"      Args: {json.dumps(args, indent=8)}")
        
        print(f"\n🔍 Now checking files registered in the system...")
        files_response = client.get('/v1/files')
        if files_response.status_code == 200:
            files = files_response.json()['data']
            plot_files = [f for f in files if f['filename'].endswith(('.png', '.jpg', '.jpeg', '.svg', '.pdf'))]
            print(f"✅ Found {len(plot_files)} plot files")
            for pf in plot_files:
                print(f"   📊 {pf['filename']} (ID: {pf['id']}, Size: {pf.get('bytes', 'unknown')} bytes)")
        else:
            print(f"❌ Failed to get files: {files_response.status_code}")
        
    except Exception as e:
        print(f"❌ Error during debug: {e}")

if __name__ == "__main__":
    debug_latest_run()