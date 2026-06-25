"""
MCP Server Build and Registration Module

This module provides comprehensive Docker-in-Docker workflows for:
1. Building and registering AWS MCP servers from the awslabs/mcp repository  
2. Building and registering custom MCP servers from any Git repository
3. Auto-generating tool configurations and Dockerfiles
4. Managing Docker registries and container lifecycle

Key Features:
- AWS MCP server templates (API, Bedrock, CDK, Terraform, CloudFormation, EKS, ECS)
- Auto-detection of project types (Node.js, Python)
- Flexible configuration system
- Integration with Agent Gateway tool registration
- Docker-in-Docker support for containerized CLI environments
"""

import asyncio
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx


class MCPBuilder:
    """
    Comprehensive MCP server build and registration system.
    
    This class implements Docker-in-Docker workflows for building MCP servers
    from source repositories and registering them with the Agent Gateway.
    """
    
    # AWS MCP server configurations from awslabs/mcp repository
    AWS_MCP_CONFIGS = {
        'api': {
            'repo': 'https://github.com/awslabs/mcp.git',
            'path': 'src/aws-api',
            'description': 'AWS API MCP Server - Comprehensive AWS API support',
            'env_vars': ['AWS_REGION', 'AWS_PROFILE'],
            'tools': ['aws_api_call', 'list_aws_resources', 'describe_resource'],
            'command': 'uvx awslabs.aws-api-mcp-server@latest'
        },
        'bedrock': {
            'repo': 'https://github.com/awslabs/mcp.git', 
            'path': 'src/bedrock-knowledge-bases-retrieval',
            'description': 'AWS Bedrock Knowledge Bases Retrieval MCP Server',
            'env_vars': ['AWS_REGION', 'BEDROCK_KB_ID'],
            'tools': ['retrieve_knowledge', 'query_bedrock_kb'],
            'command': 'uvx awslabs.bedrock-knowledge-bases-retrieval-mcp-server@latest'
        },
        'cdk': {
            'repo': 'https://github.com/awslabs/mcp.git',
            'path': 'src/cdk', 
            'description': 'AWS CDK Infrastructure Management MCP Server',
            'env_vars': ['AWS_REGION', 'CDK_APP_PATH'],
            'tools': ['cdk_deploy', 'cdk_diff', 'cdk_synthesize', 'cdk_destroy'],
            'command': 'uvx awslabs.cdk-mcp-server@latest'
        },
        'terraform': {
            'repo': 'https://github.com/awslabs/mcp.git',
            'path': 'src/terraform',
            'description': 'Terraform Infrastructure Management MCP Server', 
            'env_vars': ['AWS_REGION', 'TF_STATE_BUCKET'],
            'tools': ['terraform_plan', 'terraform_apply', 'terraform_destroy'],
            'command': 'uvx awslabs.terraform-mcp-server@latest'
        },
        'cloudformation': {
            'repo': 'https://github.com/awslabs/mcp.git',
            'path': 'src/cloudformation',
            'description': 'AWS CloudFormation MCP Server',
            'env_vars': ['AWS_REGION'],
            'tools': ['create_stack', 'update_stack', 'delete_stack', 'describe_stack'],
            'command': 'uvx awslabs.cloudformation-mcp-server@latest'
        },
        'eks': {
            'repo': 'https://github.com/awslabs/mcp.git',
            'path': 'src/eks',
            'description': 'AWS EKS Cluster Management MCP Server',
            'env_vars': ['AWS_REGION', 'EKS_CLUSTER_NAME'],
            'tools': ['create_cluster', 'update_cluster', 'delete_cluster', 'describe_cluster'],
            'command': 'uvx awslabs.eks-mcp-server@latest'
        },
        'ecs': {
            'repo': 'https://github.com/awslabs/mcp.git',
            'path': 'src/ecs', 
            'description': 'AWS ECS Container Management MCP Server',
            'env_vars': ['AWS_REGION', 'ECS_CLUSTER_NAME'],
            'tools': ['create_service', 'update_service', 'delete_service', 'describe_service'],
            'command': 'uvx awslabs.ecs-mcp-server@latest'
        }
    }
    
    def __init__(self, docker_registry: str = "localhost:5000"):
        """
        Initialize MCP Builder.
        
        Args:
            docker_registry: Docker registry for built MCP images
        """
        self.docker_registry = docker_registry
        
    async def build_aws_mcp(self, aws_mcp_type: str, gateway_url: str, api_key: str, config_file: Optional[str] = None) -> bool:
        """
        Build and register AWS MCP server using Docker-in-Docker workflow.
        
        This method implements a comprehensive build pipeline:
        1. Clone AWS MCP repository
        2. Build containerized MCP server
        3. Push to docker registry (if not localhost)
        4. Auto-generate tool configuration
        5. Register with agent gateway
        
        Args:
            aws_mcp_type: Type of AWS MCP server (api, bedrock, cdk, etc.)
            gateway_url: Agent Gateway URL
            api_key: API key for authentication
            config_file: Optional custom configuration file
            
        Returns:
            bool: True if successful, False otherwise
        """
        if aws_mcp_type not in self.AWS_MCP_CONFIGS:
            print(f"❌ Unsupported AWS MCP type: {aws_mcp_type}")
            print(f"   Available types: {', '.join(self.AWS_MCP_CONFIGS.keys())}")
            return False
            
        config = self.AWS_MCP_CONFIGS[aws_mcp_type]
        
        try:
            print(f"🚀 Building AWS MCP Server: {aws_mcp_type}")
            print(f"📁 Repository: {config['repo']}")
            print(f"📂 Path: {config['path']}")
            
            # Step 1: Clone repository in temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                success = await self._build_aws_mcp_from_repo(
                    config, aws_mcp_type, temp_dir, gateway_url, api_key, config_file
                )
                return success
                
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return False
    
    async def _build_aws_mcp_from_repo(self, config: Dict, aws_mcp_type: str, temp_dir: str, gateway_url: str, api_key: str, config_file: Optional[str]) -> bool:
        """Internal method to build AWS MCP from cloned repository."""
        temp_path = Path(temp_dir)
        repo_path = temp_path / "mcp-repo"
        
        print("📥 Cloning AWS MCP repository...")
        result = subprocess.run([
            'git', 'clone', '--depth', '1', config['repo'], str(repo_path)
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Failed to clone repository: {result.stderr}")
            return False
        
        mcp_server_path = repo_path / config['path']
        if not mcp_server_path.exists():
            print(f"❌ MCP server path not found: {config['path']}")
            print(f"   Available paths: {[p.name for p in repo_path.iterdir() if p.is_dir()]}")
            return False
        
        # Generate Dockerfile if not exists
        dockerfile_path = mcp_server_path / "Dockerfile"
        if not dockerfile_path.exists():
            dockerfile_content = self._generate_aws_dockerfile(config, aws_mcp_type)
            dockerfile_path.write_text(dockerfile_content)
            print("📝 Generated Dockerfile")
        
        # Build Docker image
        image_name = f"{self.docker_registry}/aws-mcp-{aws_mcp_type}:latest"
        print(f"🐳 Building Docker image: {image_name}")
        
        build_result = subprocess.run([
            'docker', 'build', '-t', image_name, str(mcp_server_path)
        ], capture_output=True, text=True)
        
        if build_result.returncode != 0:
            print(f"❌ Docker build failed: {build_result.stderr}")
            return False
        
        # Push to registry (if not localhost)
        if not self.docker_registry.startswith('localhost'):
            print(f"📤 Pushing to registry: {self.docker_registry}")
            push_result = subprocess.run(['docker', 'push', image_name], capture_output=True, text=True)
            if push_result.returncode != 0:
                print(f"❌ Failed to push image: {push_result.stderr}")
                return False
        
        # Generate tool configuration
        tool_config = self._generate_aws_tool_config(config, aws_mcp_type, image_name)
        
        # Register tool with agent gateway
        success = await self._register_tool_with_gateway(tool_config, gateway_url, api_key)
        if success:
            print(f"✅ Successfully registered AWS MCP server: {aws_mcp_type}")
            print(f"🔧 Tool name: {tool_config['name']}")
            print(f"🐳 Docker image: {image_name}")
            print(f"🌍 Environment variables required: {', '.join(config['env_vars'])}")
            print(f"🛠️ Available tools: {', '.join(config['tools'])}")
        
        return success
    
    def _generate_aws_dockerfile(self, config: Dict, aws_mcp_type: str) -> str:
        """Generate Dockerfile for AWS MCP server."""
        return f"""FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    curl git && \\
    rm -rf /var/lib/apt/lists/*

# Install uv for Python package management  
RUN pip install uv

WORKDIR /app

# Copy source code
COPY . .

# Install dependencies and package
RUN uv pip install --system -e .

# Set environment variables
ENV AWS_MCP_TYPE={aws_mcp_type}
ENV MCP_SERVER_PORT=8080

# Expose MCP server port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \\
    CMD curl -f http://localhost:8080/health || exit 1

# Run the MCP server
CMD {config['command']}
"""
    
    def _generate_aws_tool_config(self, config: Dict, aws_mcp_type: str, image_name: str) -> Dict:
        """Generate tool configuration for AWS MCP server."""
        return {
            "name": f"aws_{aws_mcp_type}_mcp",
            "description": config['description'],
            "invocation": {
                "protocol": "stdio",  # AWS MCP servers use stdio protocol
                "connection": {
                    "command": ["docker", "run", "--rm", "-i", 
                               "--network", "agentic_framework_network",
                               *[f"-e {var}" for var in config['env_vars']], 
                               image_name],
                    "working_directory": "/app"
                }
            },
            "args_schema": {
                "action": {"type": "string", "description": "Action to perform"},
                "parameters": {"type": "object", "description": "Action parameters"}
            },
            "acl": {
                "groups": ["admin", "aws-users"],
                "global": False
            },
            "metadata": {
                "docker_image": image_name,
                "aws_mcp_type": aws_mcp_type,
                "required_env_vars": config['env_vars'],
                "available_tools": config['tools'],
                "build_timestamp": datetime.utcnow().isoformat(),
                "source_repository": config['repo']
            }
        }
    
    async def build_custom_mcp(self, repo_url: str, gateway_url: str, api_key: str, config_file: Optional[str] = None) -> bool:
        """
        Build and register custom MCP server from any Git repository.
        
        This method provides a flexible build pipeline for any MCP server:
        1. Clone repository
        2. Detect MCP configuration (package.json, pyproject.toml, etc.)
        3. Build containerized server
        4. Auto-generate or use provided tool configuration
        5. Register with agent gateway
        
        Args:
            repo_url: Git repository URL
            gateway_url: Agent Gateway URL  
            api_key: API key for authentication
            config_file: Optional custom configuration file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print(f"🚀 Building custom MCP Server from: {repo_url}")
            
            # Extract repository name for image naming
            parsed_url = urlparse(repo_url)
            repo_name = Path(parsed_url.path).stem.replace('.git', '')
            
            # Step 1: Clone repository
            with tempfile.TemporaryDirectory() as temp_dir:
                success = await self._build_custom_mcp_from_repo(
                    repo_url, repo_name, temp_dir, gateway_url, api_key, config_file
                )
                return success
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    async def _build_custom_mcp_from_repo(self, repo_url: str, repo_name: str, temp_dir: str, gateway_url: str, api_key: str, config_file: Optional[str]) -> bool:
        """Internal method to build custom MCP from cloned repository."""
        temp_path = Path(temp_dir)
        repo_path = temp_path / "mcp-repo"
        
        print("📥 Cloning repository...")
        result = subprocess.run([
            'git', 'clone', '--depth', '1', repo_url, str(repo_path)
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Failed to clone repository: {result.stderr}")
            return False
        
        # Detect project type and generate Dockerfile
        project_type, dockerfile_content = self._detect_and_generate_dockerfile(repo_path)
        if not dockerfile_content:
            print("❌ Unable to detect project type. Please provide a Dockerfile.")
            return False
        
        dockerfile = repo_path / "Dockerfile"
        if not dockerfile.exists():
            print(f"📝 Auto-generating {project_type} Dockerfile...")
            dockerfile.write_text(dockerfile_content)
        
        # Build Docker image
        image_name = f"{self.docker_registry}/mcp-{repo_name}:latest"
        print(f"🐳 Building Docker image: {image_name}")
        
        build_result = subprocess.run([
            'docker', 'build', '-t', image_name, str(repo_path)
        ], capture_output=True, text=True)
        
        if build_result.returncode != 0:
            print(f"❌ Docker build failed: {build_result.stderr}")
            return False
        
        # Generate or load tool configuration
        tool_config = self._load_or_generate_custom_config(config_file, repo_name, image_name, repo_url)
        
        # Register tool
        success = await self._register_tool_with_gateway(tool_config, gateway_url, api_key)
        if success:
            print(f"✅ Successfully registered custom MCP server: {repo_name}")
            print(f"🔧 Tool name: {tool_config['name']}")
            print(f"🐳 Docker image: {image_name}")
        
        return success
    
    def _detect_and_generate_dockerfile(self, repo_path: Path) -> Tuple[str, Optional[str]]:
        """Detect project type and generate appropriate Dockerfile."""
        package_json = repo_path / "package.json"
        pyproject_toml = repo_path / "pyproject.toml" 
        requirements_txt = repo_path / "requirements.txt"
        
        if package_json.exists():
            # Node.js MCP server
            return "Node.js", """FROM node:18-alpine

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci --only=production

# Copy source code
COPY . .

# Expose MCP server port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \\
    CMD curl -f http://localhost:8080/health || exit 1

# Run the MCP server
CMD ["npm", "start"]
"""
        
        elif pyproject_toml.exists() or requirements_txt.exists():
            # Python MCP server
            return "Python", """FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    curl git && \\
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files
COPY requirements.txt* pyproject.toml* setup.py* ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || \\
    pip install --no-cache-dir -e . || \\
    echo "No requirements found"

# Copy source code
COPY . .

# Expose MCP server port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \\
    CMD curl -f http://localhost:8080/health || exit 1

# Run the MCP server
CMD ["python", "-m", "mcp_server"]
"""
        
        return "Unknown", None
    
    def _load_or_generate_custom_config(self, config_file: Optional[str], repo_name: str, image_name: str, repo_url: str) -> Dict:
        """Load custom configuration or generate default one."""
        if config_file and Path(config_file).exists():
            print(f"📄 Loading configuration from: {config_file}")
            with open(config_file, 'r') as f:
                return json.load(f)
        else:
            print("📝 Auto-generating tool configuration...")
            return {
                "name": f"custom_mcp_{repo_name}",
                "description": f"Custom MCP Server: {repo_name}",
                "invocation": {
                    "protocol": "stdio",  # Most custom MCP servers use stdio
                    "connection": {
                        "command": ["docker", "run", "--rm", "-i",
                                   "--network", "agentic_framework_network",
                                   image_name],
                        "working_directory": "/app"
                    }
                },
                "args_schema": {
                    "method": {"type": "string", "description": "MCP method to call"},
                    "params": {"type": "object", "description": "Method parameters"}
                },
                "acl": {
                    "groups": ["admin"],
                    "global": False
                },
                "metadata": {
                    "docker_image": image_name,
                    "source_repository": repo_url,
                    "build_timestamp": datetime.utcnow().isoformat(),
                    "project_type": "custom"
                }
            }
    
    async def _register_tool_with_gateway(self, tool_config: Dict, gateway_url: str, api_key: str) -> bool:
        """Register tool configuration with Agent Gateway."""
        try:
            print("📝 Registering tool with Agent Gateway...")
            admin_url = f"{gateway_url}/admin/tools/register"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(admin_url, json=tool_config, headers=headers)
                response.raise_for_status()
                return True
                
        except httpx.HTTPStatusError as e:
            print(f"❌ Tool registration failed: {e.response.status_code}")
            print(f"   Response: {e.response.text}")
            return False
        except Exception as e:
            print(f"❌ Registration error: {e}")
            return False
    
    def list_available_aws_types(self) -> List[str]:
        """List available AWS MCP server types."""
        return list(self.AWS_MCP_CONFIGS.keys())
    
    def get_aws_config(self, aws_mcp_type: str) -> Optional[Dict]:
        """Get configuration for specific AWS MCP type."""
        return self.AWS_MCP_CONFIGS.get(aws_mcp_type)
    
    async def pull_and_register_mcp(self, image_name: str, gateway_url: str, api_key: str, 
                                   config_file: Optional[str] = None, 
                                   tool_name: Optional[str] = None,
                                   protocol: str = "stdio") -> bool:
        """
        Pull pre-built MCP server image from registry and register as tool.
        
        This method supports the "pull and register" workflow where:
        1. MCP server images are built in CI/CD pipelines or other environments
        2. Images are stored in container registries (Docker Hub, AWS ECR, etc.)
        3. CLI pulls the image and registers it without building from source
        
        This is ideal for:
        - Production deployments with pre-built images
        - Teams using centralized CI/CD for MCP server builds
        - Registry-based distribution of MCP servers
        - Quick deployment of verified MCP server versions
        
        Args:
            image_name: Full Docker image name (e.g., 'myregistry.com/mcp-server:v1.0.0')
            gateway_url: Agent Gateway URL
            api_key: API key for authentication
            config_file: Optional path to custom tool configuration JSON file
            tool_name: Optional custom tool name (auto-generated from image if not provided)
            protocol: MCP protocol - 'stdio' (default) or 'http'
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print(f"🐳 Pulling and registering MCP server: {image_name}")
            
            # Step 1: Pull the Docker image
            print("📥 Pulling Docker image...")
            pull_result = subprocess.run([
                'docker', 'pull', image_name
            ], capture_output=True, text=True)
            
            if pull_result.returncode != 0:
                print(f"❌ Failed to pull image: {pull_result.stderr}")
                return False
            
            print(f"✅ Successfully pulled image: {image_name}")
            
            # Step 2: Inspect image to extract metadata
            inspect_result = subprocess.run([
                'docker', 'inspect', image_name
            ], capture_output=True, text=True)
            
            image_metadata = {}
            if inspect_result.returncode == 0:
                try:
                    import json as json_module
                    inspect_data = json_module.loads(inspect_result.stdout)
                    if inspect_data and len(inspect_data) > 0:
                        image_info = inspect_data[0]
                        image_metadata = {
                            'created': image_info.get('Created'),
                            'labels': image_info.get('Config', {}).get('Labels', {}),
                            'env': image_info.get('Config', {}).get('Env', []),
                            'exposed_ports': list(image_info.get('Config', {}).get('ExposedPorts', {}).keys()),
                            'size': image_info.get('Size'),
                            'architecture': image_info.get('Architecture'),
                            'os': image_info.get('Os')
                        }
                        print(f"🔍 Image metadata extracted: {len(image_metadata['labels'])} labels, {len(image_metadata['env'])} env vars")
                except Exception as e:
                    print(f"⚠️  Could not parse image metadata: {e}")
            
            # Step 3: Generate or load tool configuration  
            if config_file and Path(config_file).exists():
                print(f"📄 Loading configuration from: {config_file}")
                with open(config_file, 'r') as f:
                    tool_config = json.load(f)
                    
                # Override image in config if provided
                if 'invocation' in tool_config and 'connection' in tool_config['invocation']:
                    if protocol == "stdio" and 'command' in tool_config['invocation']['connection']:
                        # Update docker run command with new image
                        command = tool_config['invocation']['connection']['command']
                        if 'docker' in command and 'run' in command:
                            # Find and replace image name in docker run command
                            for i, arg in enumerate(command):
                                if arg.startswith(self.docker_registry) or '/' in arg and ':' in arg:
                                    command[i] = image_name
                                    break
            else:
                print("📝 Auto-generating tool configuration...")
                
                # Extract tool name from image
                if not tool_name:
                    # Generate tool name from image (e.g., 'myregistry.com/mcp-weather:v1.0' -> 'mcp_weather')
                    image_parts = image_name.split('/')
                    base_name = image_parts[-1].split(':')[0]  # Get name without tag
                    tool_name = base_name.replace('-', '_').lower()
                
                # Generate tool configuration based on protocol
                if protocol == "stdio":
                    tool_config = {
                        "name": tool_name,
                        "description": f"MCP Server: {base_name} (pulled from {image_name})",
                        "invocation": {
                            "protocol": "stdio",
                            "connection": {
                                "command": ["docker", "run", "--rm", "-i",
                                           "--network", "agentic_framework_network",
                                           image_name],
                                "working_directory": "/app"
                            }
                        },
                        "args_schema": {
                            "method": {"type": "string", "description": "MCP method to call"},
                            "params": {"type": "object", "description": "Method parameters"}
                        },
                        "acl": {
                            "groups": ["admin"],
                            "global": False
                        },
                        "metadata": {
                            "docker_image": image_name,
                            "deployment_type": "pull_and_register",
                            "pull_timestamp": datetime.utcnow().isoformat(),
                            "protocol": protocol,
                            **image_metadata  # Include extracted image metadata
                        }
                    }
                elif protocol == "http":
                    # For HTTP protocol, assume the container exposes port 8080
                    port = "8080"
                    if image_metadata.get('exposed_ports'):
                        # Use first exposed port
                        exposed_port = list(image_metadata['exposed_ports'])[0]
                        port = exposed_port.split('/')[0]
                    
                    tool_config = {
                        "name": tool_name,
                        "description": f"HTTP MCP Server: {base_name} (pulled from {image_name})",
                        "invocation": {
                            "protocol": "http",
                            "connection": {
                                "url": f"http://{tool_name}:{port}/mcp",
                                "method": "POST",
                                "headers": {
                                    "Content-Type": "application/json"
                                }
                            }
                        },
                        "args_schema": {
                            "action": {"type": "string", "description": "Action to perform"},
                            "parameters": {"type": "object", "description": "Action parameters"}
                        },
                        "acl": {
                            "groups": ["admin"],
                            "global": False
                        },
                        "metadata": {
                            "docker_image": image_name,
                            "deployment_type": "pull_and_register",
                            "pull_timestamp": datetime.utcnow().isoformat(),
                            "protocol": protocol,
                            "service_port": port,
                            **image_metadata
                        }
                    }
                else:
                    print(f"❌ Unsupported protocol: {protocol}. Supported: stdio, http")
                    return False
            
            # Step 4: Register tool with agent gateway
            success = await self._register_tool_with_gateway(tool_config, gateway_url, api_key)
            if success:
                print(f"✅ Successfully registered MCP server from image")
                print(f"🔧 Tool name: {tool_config['name']}")
                print(f"🐳 Docker image: {image_name}")
                print(f"📡 Protocol: {protocol}")
                
                # Show useful metadata
                if image_metadata.get('labels'):
                    print(f"🏷️  Image labels: {len(image_metadata['labels'])}")
                if image_metadata.get('size'):
                    size_mb = image_metadata['size'] / (1024 * 1024)
                    print(f"📊 Image size: {size_mb:.1f} MB")
                if image_metadata.get('architecture'):
                    print(f"🏗️  Architecture: {image_metadata['architecture']}")
            
            return success
        
        except subprocess.CalledProcessError as e:
            print(f"❌ Docker command failed: {e}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return False


# Convenience functions for CLI integration
async def build_and_register_aws_mcp(aws_mcp_type: str, gateway_url: str, api_key: str, 
                                     docker_registry: str = "localhost:5000", 
                                     config_file: Optional[str] = None) -> bool:
    """Build and register AWS MCP server."""
    builder = MCPBuilder(docker_registry)
    return await builder.build_aws_mcp(aws_mcp_type, gateway_url, api_key, config_file)


async def build_and_register_custom_mcp(repo_url: str, gateway_url: str, api_key: str,
                                        docker_registry: str = "localhost:5000", 
                                        config_file: Optional[str] = None) -> bool:
    """Build and register custom MCP server."""  
    builder = MCPBuilder(docker_registry)
    return await builder.build_custom_mcp(repo_url, gateway_url, api_key, config_file)


async def pull_and_register_mcp(image_name: str, gateway_url: str, api_key: str, 
                                config_file: Optional[str] = None, 
                                tool_name: Optional[str] = None,
                                protocol: str = "stdio") -> bool:
    """
    Pull pre-built MCP server image and register as tool.
    
    This function supports the "pull and register" workflow for MCP servers
    that have been built elsewhere (e.g., in CI/CD pipelines, other registries).
    
    Args:
        image_name: Docker image name (e.g., 'registry.com/my-mcp-server:latest')
        gateway_url: Agent Gateway URL
        api_key: API key for authentication
        config_file: Optional custom configuration file
        tool_name: Optional custom tool name (auto-generated if not provided)
        protocol: MCP protocol (stdio, http)
        
    Returns:
        bool: True if successful, False otherwise
    """
    builder = MCPBuilder()
    return await builder.pull_and_register_mcp(image_name, gateway_url, api_key, config_file, tool_name, protocol)


def list_aws_mcp_types() -> List[str]:
    """List available AWS MCP server types."""
    builder = MCPBuilder()
    return builder.list_available_aws_types()