"""
Enhanced CLI Chat Client - Response API with Admin Privileges and Local Command Execution

This module provides a modern command-line interface (CLI) for interacting with
the Agent Gateway, featuring local command execution capabilities similar to
the Gemini and Claude CLIs.

Key Features:
- **LLM-based Command Validation:** A safety layer that uses an LLM to check for
  potentially malicious commands before they are presented to the user.
- **Local Command Execution:** Agent can request to run shell commands on the user's machine.
- **User Confirmation:** All local commands require explicit user approval for security.
- **Response API Integration:** Uses OpenAI-compatible chat completions endpoint.
- **Streaming Support:** Real-time response streaming for the agent's final answer.
- **Advanced CLI Features:** Path autocompletion, command history, color-coded output.
"""
import os
import re
import openai
import requests
import logging
import mimetypes
import time
import json
import subprocess
import glob
import argparse
import asyncio
import httpx
import jwt
from typing import List, Dict

# prompt-toolkit for advanced CLI features
from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.completion import PathCompleter, Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)

# Define a color scheme for the chat interface
style = Style.from_dict({
    'prompt': 'ansiblue bold',
    'agent': 'ansigreen bold',
    'warning': 'ansiyellow bold',
    'command': 'ansicyan',
    'error': 'ansired bold',
})

class AtFileCompleter(Completer):
    """
    Custom completer for `prompt-toolkit` that triggers path completion after an '@'.
    """
    def __init__(self):
        self.path_completer = PathCompleter()

    def get_completions(self, document, complete_event):
        """
        Yields path completions if the text before the cursor contains an '@'.
        """
        text = document.text_before_cursor
        if '@' in text:
            path_prefix = text.rsplit('@', 1)[-1]
            path_document = document.__class__(text=path_prefix, cursor_position=len(path_prefix))
            for completion in self.path_completer.get_completions(path_document, complete_event):
                yield completion

class AgentChatClient:
    """
    Enhanced CLI client with local command execution capabilities.
    """

    def __init__(self, base_url: str, api_key: str, model_name: str, use_streaming: bool = True, username: str = None):
        """
        Initializes the Response API chat client.
        """
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.use_streaming = use_streaming
        self.username = username or "default-user"  # Store username for session management
        
        response_api_url = f"{base_url}/responses" if not base_url.endswith('/responses') else base_url
        self.client = openai.OpenAI(base_url=response_api_url, api_key=api_key)
        
        self.conversation_history = []
        self.session = None # Will be initialized in start_chat

        # Define the tool the agent can use
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "local_shell",
                    "description": "Executes a shell command on the user's local machine. Use this to list files, check configurations, or run scripts as requested by the user. The user will be prompted for confirmation before execution.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The shell command to execute (e.g., 'ls -l', 'cat my_file.txt')."
                            }
                        },
                        "required": ["command"]
                    }
                }
            }
        ]
        
        logger.info("Initialized Response API client with local command execution enabled")
        logger.info(f"Base URL: {response_api_url}")
        logger.info(f"Model: {model_name}")
        logger.info(f"Streaming: {use_streaming}")

    def _initialize_conversation(self):
        """
        Initialize conversation with system message.
        """
        if not self.conversation_history:
            system_message = {
                "role": "system",
                "content": (
                    "You are an advanced scientific workflow assistant. You have the ability to request the execution of shell commands on the user's local machine to explore the file system, run scripts, or perform other tasks. Use the 'local_shell' tool for this purpose. The user will always be asked for permission before a command is executed. You also have access to other comprehensive tools for bioinformatics, web search, and data processing."
                )
            }
            self.conversation_history.append(system_message)
            logger.info("Initialized conversation with system context")

    @staticmethod
    def get_user_token() -> str:
        """
        Authenticates with Keycloak to get a user JWT using the password grant type.
        
        This uses the 'login-client' and 'notebook-user' credentials, which are
        configured to issue standard, user-centric JWTs with the necessary claims
        (like 'sub' and 'aud') that the Agent Gateway expects for validation.
        """
        keycloak_url = os.getenv('KEYCLOAK_URL', 'http://localhost:8180')
        keycloak_realm = os.getenv('KEYCLOAK_REALM', 'master')
        token_url = f"{keycloak_url}/realms/{keycloak_realm}/protocol/openid-connect/token"
        
        payload = {
            'client_id': 'login-client',
            'username': 'notebook-user',
            'password': 'notebook-password',
            'grant_type': 'password'
        }
        
        logger.info("Attempting to fetch user JWT...")
        try:
            response = requests.post(token_url, data=payload)
            response.raise_for_status()
            token_data = response.json()
            logger.info("Successfully obtained user JWT.")
            return token_data['access_token']
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get admin token from {token_url}. Is Keycloak running?")
            logger.error(f"Details: {e}")
            return None

    async def _is_command_safe(self, command: str) -> bool:
        """
        Uses an LLM to validate if a command is safe to execute.
        """
        logger.info(f"Validating safety of command: {command}")
        try:
            validator_system_prompt = """
            You are a security expert responsible for validating shell commands.
            Your task is to determine if a command is safe to execute.
            A command is considered "safe" if it is read-only and does not modify the filesystem,
            system state, or network configuration. It must not download or execute remote scripts.
            
            Examples of safe commands: ls, cat, grep, rg, find, echo, pwd, git status, docker ps
            Examples of unsafe commands: rm, mv, cp, sudo, chmod, chown, mkdir, touch, curl | bash, pip install, apt-get, any command that writes to a file (>)
            
            Analyze the following command. Respond with only the word "SAFE" if it is safe,
            or "UNSAFE" if it is not. Do not provide any explanation.
            """
            
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": validator_system_prompt},
                    {"role": "user", "content": command}
                ],
                temperature=0,
                max_tokens=5,
                stream=False
            )
            
            decision = response.choices[0].message.content.strip().upper()
            logger.info(f"LLM validator decision: '{decision}' for command: '{command}'")
            
            return decision == "SAFE"
        except Exception as e:
            logger.error(f"An error occurred during command validation: {e}", exc_info=True)
            # Default to unsafe on error
            return False

    def _send_message(self, user_input: str):
        """
        Sends a message and handles the full tool-use conversation flow.
        """
        self._initialize_conversation()
        
        self.conversation_history.append({"role": "user", "content": user_input})
        
        try:
            while True:
                logger.info("Sending request to agent to get next action...")
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=self.conversation_history,
                    tools=self.tools,
                    tool_choice="auto",
                    stream=False
                )
                
                response_message = response.choices[0].message
                
                if response_message.tool_calls:
                    logger.info(f"Agent requested {len(response_message.tool_calls)} tool call(s).")
                    self.conversation_history.append(response_message)
                    
                    tool_responses = self._execute_tool_calls(response_message.tool_calls)
                    
                    for tool_response in tool_responses:
                        self.conversation_history.append(tool_response)
                    
                    continue
                else:
                    logger.info("Agent provided a final text response.")
                    self.conversation_history.append(response_message)
                    
                    if self.use_streaming:
                        self._handle_streaming_final_response()
                    else:
                        assistant_response = response_message.content
                        response_text = FormattedText([('class:agent', 'Agent: '), ('', assistant_response)])
                        print_formatted_text(response_text, style=style)
                    break
        except Exception as e:
            error_msg = f"Error communicating with agent: {str(e)}"
            logger.error(error_msg, exc_info=True)
            print(f"\nAn error occurred: {e}")

    def _handle_streaming_final_response(self):
        """
        Performs a final streaming call to get the agent's text response after any tool use.
        """
        logger.info("Initiating streaming for final agent response...")
        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.conversation_history,
                stream=True
            )
            
            full_response = ""
            response_text = FormattedText([('class:agent', 'Agent: ')])
            print_formatted_text(response_text, style=style, end="")
            
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content is not None:
                    full_response += content
                    print(content, end="", flush=True)
            
            print()
            
            self.conversation_history[-1]["content"] = full_response
        except Exception as e:
            logger.error(f"Streaming error on final response: {e}", exc_info=True)

    def _execute_tool_calls(self, tool_calls: list) -> list:
        """
        Validates and executes tool calls requested by the agent after user confirmation.
        """
        tool_responses = []
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            
            try:
                function_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                logger.error(f"Failed to decode tool arguments: {tool_call.function.arguments}")
                tool_output = "Error: Invalid arguments provided by the agent."
                function_args = {}
            
            command = function_args.get("command")
            tool_output = ""

            if function_name != "local_shell" or not command:
                tool_output = f"Error: Client received request for unknown tool '{function_name}' or command was missing."
                logger.warning(tool_output)
            else:
                # LLM-based safety validation
                import asyncio
                is_safe = asyncio.run(self._is_command_safe(command))
                
                if not is_safe:
                    tool_output = "Error: Command was blocked by the security validator."
                    print_formatted_text(FormattedText([
                        ('class:error', "Blocked unsafe command: "),
                        ('class:command', command)
                    ]), style=style)
                else:
                    # User confirmation
                    print_formatted_text(FormattedText([
                        ('class:warning', "Agent wants to run command: "),
                        ('class:command', command)
                    ]), style=style)
                    
                    confirm = self.session.prompt("Execute? [Y/n]: ").strip().lower()
                    
                    if confirm not in ["y", "yes", ""]:
                        print("Execution cancelled by user.")
                        logger.info(f"User denied execution of command: {command}")
                        tool_output = "User denied execution."
                    else:
                        logger.info(f"User approved execution of command: {command}")
                        try:
                            result = subprocess.run(
                                command, shell=True, capture_output=True, text=True, timeout=120
                            )
                            tool_output = (
                                f"Exit Code: {result.returncode}\n"
                                f"--- STDOUT ---\n{result.stdout}\n"
                                f"--- STDERR ---\n{result.stderr}"
                            )
                            logger.info(f"Command executed with exit code {result.returncode}")
                        except Exception as e:
                            tool_output = f"An error occurred while executing the command: {str(e)}"
                            logger.error(f"Error executing command '{command}': {e}", exc_info=True)

            tool_responses.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": tool_output,
            })
        return tool_responses

    def start_chat(self):
        """
        Starts the enhanced interactive chat loop.
        """
        logger.info("🚀 Enhanced Agent Chat Client with Local Command Execution")
        logger.info("🔒 LLM-based command validation is ENABLED.")
        logger.info("⚡ Agent can request to run local commands. You will be prompted for approval.")
        logger.info("📁 Use '@' to upload local files (e.g., 'Analyze @my_data.csv').")
        logger.info("🚪 Type 'exit', 'quit', or press Ctrl+C to end.")
        logger.info("💡 Type '/clear' to clear history, '/help' for commands, '/tools' for tool management.")
        logger.info("-" * 60)
        
        history = FileHistory(os.path.expanduser('~/.agent_chat_history'))
        self.session = PromptSession(history=history, completer=AtFileCompleter(), complete_while_typing=True, style=style)
        debug_mode = False

        try:
            while True:
                prompt_text = FormattedText([('class:prompt', 'You: ')])
                user_input = self.session.prompt(prompt_text).strip()
                
                if user_input.lower() in ["exit", "quit"]:
                    break
                if user_input.lower() == "/clear":
                    self.conversation_history = []
                    logger.info("✨ Conversation history cleared")
                    continue
                if user_input.lower() == "/debug":
                    debug_mode = not debug_mode
                    logger.info(f"🐛 Debug mode: {'Enabled' if debug_mode else 'Disabled'}")
                    continue
                if user_input.lower() == "/help":
                    self._show_help()
                    continue
                if user_input.lower() == "/tools":
                    self._show_tools_menu()
                    continue
                if user_input.lower().startswith("/tools "):
                    self._handle_tool_command(user_input[7:])
                    continue
                if not user_input:
                    continue

                if debug_mode:
                    logger.info(f"Debug - Conversation length: {len(self.conversation_history)}")
                    logger.info(f"Debug - User input: {user_input}")

                file_patterns = re.findall(r'@(\S+)', user_input)
                if file_patterns:
                    self.upload_files(file_patterns)
                
                self._send_message(user_input)

        except KeyboardInterrupt:
            pass
        finally:
            print("\n👋 Exiting enhanced chat session. Goodbye!")
            
    def _show_tools_menu(self):
        """Display tool management menu."""
        print("""
🔧 Tool Management Commands:
  /tools list              - List all registered tools
  /tools register <file>   - Register a tool from JSON file
  /tools delete <name>     - Delete a registered tool
  /tools show <name>       - Show details of a specific tool
  
Examples:
  /tools list
  /tools register my_tool.json
  /tools delete my_custom_tool
  /tools show execute_code
        """)
    
    def _handle_tool_command(self, command: str):
        """Handle tool management commands."""
        parts = command.strip().split()
        if not parts:
            self._show_tools_menu()
            return
            
        subcommand = parts[0].lower()
        
        try:
            if subcommand == "list":
                asyncio.run(self._list_tools_interactive())
            elif subcommand == "register" and len(parts) >= 2:
                config_file = parts[1]
                asyncio.run(self._register_tool_interactive(config_file))
            elif subcommand == "delete" and len(parts) >= 2:
                tool_name = parts[1]
                asyncio.run(self._delete_tool_interactive(tool_name))
            elif subcommand == "show" and len(parts) >= 2:
                tool_name = parts[1]
                asyncio.run(self._show_tool_interactive(tool_name))
            else:
                print("❌ Invalid tool command. Type '/tools' for help.")
        except Exception as e:
            print(f"❌ Error executing tool command: {e}")
    
    async def _list_tools_interactive(self):
        """List tools interactively during chat."""
        await list_registered_tools(self.base_url, self.api_key)
    
    async def _register_tool_interactive(self, config_file: str):
        """Register a tool interactively during chat."""
        success = await register_tool_from_file(config_file, self.base_url, self.api_key)
        if success:
            print("🎉 Tool registration completed. It's now available to the agent!")
    
    async def _delete_tool_interactive(self, tool_name: str):
        """Delete a tool interactively during chat."""
        try:
            base_url = self.base_url.replace('/v1', '')
            admin_url = f"{base_url}/v1/tools/{tool_name}"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            # Confirm deletion
            confirm = input(f"❓ Are you sure you want to delete tool '{tool_name}'? [y/N]: ").strip().lower()
            if confirm not in ['y', 'yes']:
                print("⏹️ Tool deletion cancelled.")
                return
            
            async with httpx.AsyncClient() as client:
                response = await client.delete(admin_url, headers=headers)
                response.raise_for_status()
                print(f"✅ Tool '{tool_name}' deleted successfully.")
        except httpx.HTTPStatusError as e:
            print(f"❌ HTTP error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            print(f"❌ Error deleting tool: {e}")
    
    async def _show_tool_interactive(self, tool_name: str):
        """Show detailed information about a specific tool."""
        try:
            base_url = self.base_url.replace('/v1', '')
            admin_url = f"{base_url}/v1/tools/list"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(admin_url, headers=headers)
                response.raise_for_status()
                tools = response.json()
                
                # Find the specific tool
                tool = next((t for t in tools if t.get('name') == tool_name), None)
                if not tool:
                    print(f"❌ Tool '{tool_name}' not found.")
                    return
                
                print(f"\n🔧 Tool: {tool.get('name', 'Unknown')}")
                print(f"📋 Type: {tool.get('type', 'Unknown')}")
                if tool.get('description'):
                    print(f"📝 Description: {tool['description']}")
                if tool.get('url'):
                    print(f"🌐 URL: {tool['url']}")
                if tool.get('acl', {}).get('groups'):
                    print(f"👥 Access Groups: {', '.join(tool['acl']['groups'])}")
                if tool.get('schema'):
                    print(f"📄 Schema: {json.dumps(tool['schema'], indent=2)}")
                print()
                
        except httpx.HTTPStatusError as e:
            print(f"❌ HTTP error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            print(f"❌ Error showing tool: {e}")

    def _show_help(self):
        """Display help information."""
        print("""
🔧 Enhanced Chat Client Commands:
  /clear         - Clear conversation history
  /debug         - Toggle debug mode
  /help          - Show this help message
  /tools         - Tool management menu
  /tools list    - List registered tools
  exit/quit      - Exit the chat session
  
📁 File Upload:
  @filename - Upload and reference a file
  
🛠️ Tool Management:
  /tools register <file>  - Register tool from JSON config
  /tools delete <name>    - Delete a registered tool
  /tools show <name>      - Show tool details
  
⚡ Local Commands:
  The agent can ask for permission to run commands like 'ls' or 'cat'
  on your machine. A security validator will check commands first.
  You must approve each validated command before it runs.
        """)

    def upload_files(self, file_patterns: List[str]):
        """
        Expands glob patterns and uploads all matching files.
        """
        logger.info(f"Attempting to upload files for patterns: {file_patterns}")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        upload_url = f"{self.base_url.replace('/v1', '')}/v1/files"

        all_files_to_upload = []
        for pattern in file_patterns:
            expanded_paths = glob.glob(pattern, recursive=True)
            if not expanded_paths:
                logger.warning(f"Pattern '{pattern}' did not match any files.")
                continue
            all_files_to_upload.extend(expanded_paths)

        if not all_files_to_upload:
            logger.info("No files found to upload after expanding patterns.")
            return

        logger.info(f"Found {len(all_files_to_upload)} total files to upload.")

        for file_path in all_files_to_upload:
            if os.path.isdir(file_path):
                logger.warning(f"Skipping directory: {file_path}")
                continue
            
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}. Skipping.")
                continue

            mime_type, _ = mimetypes.guess_type(file_path)
            purpose = "vision" if mime_type and mime_type.startswith("image/") else "assistants"
            
            logger.info(f"Uploading '{file_path}' (MIME: {mime_type}, Purpose: {purpose})...")

            try:
                with open(file_path, "rb") as f:
                    files = {"file": (os.path.basename(file_path), f, mime_type)}
                    data = {"purpose": purpose, "session_id": self.username}  # Use username as session ID
                    response = requests.post(upload_url, headers=headers, files=files, data=data)
                    response.raise_for_status()
                    file_id = response.json().get('id')
                    logger.info(f"Successfully uploaded '{file_path}' to session '{self.username}'. File ID: {file_id}")
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to upload '{file_path}'. Error: {e.response.text if e.response else e}")
            except Exception as e:
                logger.error(f"An unexpected error occurred during upload of '{file_path}': {e}")

def parse_arguments():
    """Parse command-line arguments for stack configuration and tool management."""
    parser = argparse.ArgumentParser(
        description="Enhanced CLI Chat Client with Multi-Stack Support and Tool Registration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Stack Configuration Examples:
  # Connect to default stack
  python chat_client.py
  
  # Connect to specific stack
  python chat_client.py --stack stack_b --port 8183
  
  # Connect to custom gateway URL
  python chat_client.py --gateway-url http://localhost:8283/v1
  
  # Register a tool from JSON file
  python chat_client.py --register-tool my_tool.json
        """
    )
    
    # Stack configuration
    parser.add_argument("--stack", "--stack-id", 
                       help="Stack ID for multi-stack deployment (e.g., stack_a, stack_b)")
    parser.add_argument("--port", type=int,
                       help="Agent Gateway port (overrides default port calculation)")
    parser.add_argument("--gateway-url", 
                       help="Full Agent Gateway URL (overrides stack-based URL generation)")
    parser.add_argument("--keycloak-url",
                       help="Keycloak server URL (default: http://localhost:8180)")
    
    # Tool registration and MCP build workflow
    tool_group = parser.add_argument_group("Tool Management")
    tool_group.add_argument("--register-tool", metavar="CONFIG_FILE",
                       help="Register a tool from JSON configuration file and exit")
    tool_group.add_argument("--list-tools", action="store_true",
                       help="List all registered tools and exit")
    tool_group.add_argument("--build-mcp", metavar="REPO_URL",
                       help="Build and register MCP server from Git repository URL")
    tool_group.add_argument("--aws-mcp", choices=['api', 'bedrock', 'cdk', 'terraform', 'cloudformation', 'eks', 'ecs'],
                       help="Build and register AWS MCP server (requires Docker-in-Docker)")
    tool_group.add_argument("--pull-mcp", metavar="IMAGE_NAME",
                       help="Pull pre-built MCP server image and register as tool")
    tool_group.add_argument("--mcp-config", metavar="CONFIG_FILE",
                       help="Path to MCP server configuration file for build process")
    tool_group.add_argument("--mcp-protocol", choices=['stdio', 'http'], default='stdio',
                       help="MCP protocol for tool registration (default: stdio)")
    tool_group.add_argument("--tool-name", metavar="NAME",
                       help="Custom tool name (auto-generated if not provided)")
    tool_group.add_argument("--docker-registry", default="localhost:5000",
                       help="Docker registry for built MCP images (default: localhost:5000)")
    
    # Other options
    parser.add_argument("--no-streaming", action="store_true",
                       help="Disable response streaming")
    parser.add_argument("--model", 
                       help="Model name (default: from AGENT_MODEL_NAME env var)")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    
    return parser.parse_args()

def calculate_stack_config(args):
    """Calculate stack-specific configuration from arguments."""
    # Default values
    default_gateway_url = os.getenv("AGENT_GATEWAY_URL", "http://localhost:8083/v1")
    default_keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:8180")
    
    # If gateway URL is explicitly provided, use it
    if args.gateway_url:
        return args.gateway_url, args.keycloak_url or default_keycloak_url
    
    # If stack ID is provided, calculate URLs
    if args.stack:
        # Stack-specific port calculation
        if args.port:
            gateway_port = args.port
        else:
            # Default port mapping for known stacks
            stack_ports = {
                'stack_a': 8083,
                'stack_b': 8183, 
                'stack_c': 8283,
                'stack_d': 8383
            }
            gateway_port = stack_ports.get(args.stack, 8083 + hash(args.stack) % 1000)
        
        gateway_url = f"http://localhost:{gateway_port}/v1"
        keycloak_url = args.keycloak_url or default_keycloak_url
        return gateway_url, keycloak_url
    
    # Use defaults
    return default_gateway_url, default_keycloak_url

async def register_tool_from_file(config_file: str, gateway_url: str, api_key: str):
    """Register a tool from JSON configuration file."""
    try:
        with open(config_file, 'r') as f:
            tool_config = json.load(f)
        
        # Remove /v1 from gateway URL for admin endpoint
        base_url = gateway_url.replace('/v1', '')
        admin_url = f"{base_url}/v1/tools/register"
        
        headers = {"Authorization": f"Bearer {api_key}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(admin_url, json=tool_config, headers=headers)
            response.raise_for_status()
            print(f"✅ Tool '{tool_config.get('name', 'unknown')}' registered successfully.")
            return True
    except FileNotFoundError:
        print(f"❌ Configuration file not found: {config_file}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in configuration file: {e}")
        return False
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP error {e.response.status_code}: {e.response.text}")
        return False
    except Exception as e:
        print(f"❌ Error registering tool: {e}")
        return False

async def list_registered_tools(gateway_url: str, api_key: str):
    """List all registered tools."""
    try:
        base_url = gateway_url.replace('/v1', '')
        admin_url = f"{base_url}/v1/tools/list"
        
        headers = {"Authorization": f"Bearer {api_key}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(admin_url, headers=headers)
            response.raise_for_status()
            tools = response.json()
            
            if not tools:
                print("📝 No registered tools found.")
                return
                
            print(f"📝 Found {len(tools)} registered tools:")
            for tool in tools:
                print(f"  • {tool.get('name', 'unknown')} ({tool.get('type', 'unknown')})")
                if tool.get('description'):
                    print(f"    {tool['description'][:100]}...")
                if tool.get('acl', {}).get('groups'):
                    print(f"    👥 Access: {', '.join(tool['acl']['groups'])}")
                print()
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP error {e.response.status_code}: {e.response.text}")
    except Exception as e:
        print(f"❌ Error listing tools: {e}")

from .mcp_builder import (
    build_and_register_aws_mcp, 
    build_and_register_custom_mcp, 
    pull_and_register_mcp,
    list_aws_mcp_types
)

if __name__ == "__main__":
    args = parse_arguments()
    
    # Enable debug logging if requested
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Calculate stack-specific configuration
    gateway_url, keycloak_url = calculate_stack_config(args)
    model_name = args.model or os.getenv("AGENT_MODEL_NAME", "agentic-framework:scientific-agent-v1")
    use_streaming = not args.no_streaming
    
    # Set Keycloak URL environment variable for authentication
    os.environ["KEYCLOAK_URL"] = keycloak_url
    
    logger.info("🔐 CLI Client - Authenticating as standard user...")
    API_KEY = AgentChatClient.get_user_token()
    
    if not API_KEY:
        logger.error("❌ Could not obtain user API key (JWT token). Exiting.")
        logger.error("   Please ensure Keycloak is running and user credentials are configured.")
        logger.error(f"   Keycloak URL: {keycloak_url}")
        exit(1)
    
    # Handle tool registration commands
    if args.register_tool:
        logger.info(f"🔧 Registering tool from: {args.register_tool}")
        success = asyncio.run(register_tool_from_file(args.register_tool, gateway_url, API_KEY))
        exit(0 if success else 1)
    
    if args.list_tools:
        logger.info("📋 Listing registered tools...")
        asyncio.run(list_registered_tools(gateway_url, API_KEY))
        exit(0)
    
    # Handle MCP build and register workflows
    if args.aws_mcp:
        logger.info(f"🚀 Building AWS MCP server: {args.aws_mcp}")
        success = asyncio.run(build_and_register_aws_mcp(
            args.aws_mcp, gateway_url, API_KEY, 
            args.docker_registry, args.mcp_config
        ))
        exit(0 if success else 1)
    
    if args.build_mcp:
        logger.info(f"🚀 Building custom MCP server from: {args.build_mcp}")
        success = asyncio.run(build_and_register_custom_mcp(
            args.build_mcp, gateway_url, API_KEY,
            args.docker_registry, args.mcp_config
        ))
        exit(0 if success else 1)
    
    if args.pull_mcp:
        logger.info(f"🐳 Pulling and registering MCP server: {args.pull_mcp}")
        success = asyncio.run(pull_and_register_mcp(
            args.pull_mcp, gateway_url, API_KEY,
            args.mcp_config, args.tool_name, args.mcp_protocol
        ))
        exit(0 if success else 1)
    
    # Start interactive chat
    logger.info("✅ User authentication successful")
    logger.info(f"🎯 Target: {gateway_url}")
    logger.info(f"🔐 Keycloak: {keycloak_url}")
    logger.info(f"🧠 Model: {model_name}")
    
    # Extract username from JWT for session management
    try:
        decoded_token = jwt.decode(API_KEY, options={"verify_signature": False})
        username = decoded_token.get("preferred_username", "default-user")
        logger.info(f"👤 Session User: {username}")
    except Exception as e:
        logger.warning(f"Could not decode JWT for username: {e}")
        username = "default-user"
    if args.stack:
        logger.info(f"📦 Stack: {args.stack}")
    
    chat_client = AgentChatClient(
        base_url=gateway_url,
        api_key=API_KEY,
        model_name=model_name,
        use_streaming=use_streaming,
        username=username
    )
    
    try:
        chat_client.start_chat()
    except Exception as e:
        logger.error(f"❌ Fatal error in chat client: {e}", exc_info=True)
        exit(1)