#!/usr/bin/env python3
"""
Service Health Manager

Manages service credential health, MCP tool discovery validation,
and provides health check endpoints for monitoring service integrity.

This script addresses two critical issues:
1. Service client credential drift (OpenWebUI, n8n losing auth)
2. MCP tool discovery validation and health monitoring

Usage:
  python scripts/deps/service_health_manager.py --validate-credentials
  python scripts/deps/service_health_manager.py --discover-tools  
  python scripts/deps/service_health_manager.py --health-check
  python scripts/deps/service_health_manager.py --fix-credentials
"""
import asyncio
import argparse
import sys
import os
import json
from typing import Dict, Any

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../src')))

from agentic_framework_pkg.core.service_credentials_manager import credentials_manager
from agentic_framework_pkg.core.mcp_tool_discovery import mcp_discovery
from agentic_framework_pkg.logger_config import get_logger

logger = get_logger(__name__)

class ServiceHealthManager:
    """Comprehensive service health management and validation"""
    
    def __init__(self):
        self.credentials_manager = credentials_manager
        self.mcp_discovery = mcp_discovery
    
    async def validate_all_credentials(self) -> Dict[str, Any]:
        """Validate all service client credentials"""
        logger.info("🔍 Validating service credentials...")
        
        # Initialize credentials manager
        init_success = await self.credentials_manager.initialize()
        if not init_success:
            logger.error("❌ Failed to initialize credentials manager")
            return {"status": "failed", "error": "initialization_failed"}
        
        # Get health check results
        health_status = await self.credentials_manager.health_check()
        
        # Analyze results
        total_services = len(health_status)
        healthy_services = sum(1 for service in health_status.values() 
                             if service["health_status"] == "healthy")
        
        logger.info(f"📊 Credential Health: {healthy_services}/{total_services} services healthy")
        
        # Print detailed status
        for service_name, status in health_status.items():
            status_emoji = "✅" if status["health_status"] == "healthy" else "❌"
            logger.info(f"{status_emoji} {service_name}: {status['health_status']}")
            
            if status["health_status"] != "healthy":
                logger.warning(f"   Details: {status}")
        
        return {
            "status": "success",
            "total_services": total_services,
            "healthy_services": healthy_services,
            "health_details": health_status
        }
    
    async def fix_credentials(self) -> Dict[str, Any]:
        """Attempt to fix credential issues"""
        logger.info("🔧 Attempting to fix credential issues...")
        
        await self.credentials_manager.initialize()
        health_status = await self.credentials_manager.health_check()
        
        fixed_services = []
        failed_services = []
        
        for service_name, status in health_status.items():
            if status["health_status"] != "healthy":
                logger.info(f"🔧 Attempting to fix {service_name}...")
                
                try:
                    # Ensure client exists in Keycloak
                    client_created = await self.credentials_manager.ensure_client_exists(service_name)
                    
                    if client_created:
                        # Get fresh token
                        token = await self.credentials_manager.get_valid_token(service_name)
                        
                        if token:
                            fixed_services.append(service_name)
                            logger.info(f"✅ Fixed credentials for {service_name}")
                        else:
                            failed_services.append(service_name)
                            logger.error(f"❌ Failed to get token for {service_name}")
                    else:
                        failed_services.append(service_name)
                        logger.error(f"❌ Failed to ensure client exists for {service_name}")
                        
                except Exception as e:
                    logger.error(f"❌ Exception fixing {service_name}: {e}")
                    failed_services.append(service_name)
        
        logger.info(f"🎯 Credential fix results: {len(fixed_services)} fixed, {len(failed_services)} failed")
        
        return {
            "status": "completed",
            "fixed_services": fixed_services,
            "failed_services": failed_services
        }
    
    async def discover_mcp_tools(self) -> Dict[str, Any]:
        """Discover and validate MCP tool availability"""
        logger.info("🔍 Discovering MCP tools...")
        
        try:
            # Force fresh discovery
            discovered_tools = await self.mcp_discovery.discover_all_tools(force_refresh=True)
            
            # Get server health
            server_health = await self.mcp_discovery.get_server_health()
            
            # Analyze results
            total_tools = len(discovered_tools)
            tools_by_server = {}
            
            for tool in discovered_tools:
                if tool.server not in tools_by_server:
                    tools_by_server[tool.server] = []
                tools_by_server[tool.server].append({
                    "name": tool.name,
                    "description": tool.description,
                    "discovery_method": tool.metadata.get("discovery_method", "unknown") if tool.metadata else "unknown"
                })
            
            logger.info(f"📊 Tool Discovery: {total_tools} tools discovered from {len(tools_by_server)} servers")
            
            # Print server status
            for server_name, health in server_health.items():
                status_emoji = "✅" if health["status"] == "healthy" else "❌"
                tool_count = len(tools_by_server.get(server_name, []))
                logger.info(f"{status_emoji} {server_name}: {health['status']} ({tool_count} tools)")
            
            return {
                "status": "success",
                "total_tools": total_tools,
                "tools_by_server": tools_by_server,
                "server_health": server_health
            }
            
        except Exception as e:
            logger.error(f"❌ MCP tool discovery failed: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}
    
    async def comprehensive_health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check of all services"""
        logger.info("🩺 Performing comprehensive health check...")
        
        # Check credentials
        cred_results = await self.validate_all_credentials()
        
        # Check MCP tools
        tool_results = await self.discover_mcp_tools()
        
        # Overall health assessment
        overall_healthy = (
            cred_results.get("status") == "success" and
            cred_results.get("healthy_services", 0) == cred_results.get("total_services", 1) and
            tool_results.get("status") == "success" and
            tool_results.get("total_tools", 0) > 0
        )
        
        health_summary = {
            "overall_status": "healthy" if overall_healthy else "degraded",
            "timestamp": self._get_timestamp(),
            "credentials": cred_results,
            "mcp_tools": tool_results,
            "recommendations": self._get_health_recommendations(cred_results, tool_results)
        }
        
        # Print summary
        status_emoji = "✅" if overall_healthy else "⚠️"
        logger.info(f"{status_emoji} Overall Health: {health_summary['overall_status']}")
        
        if health_summary["recommendations"]:
            logger.info("💡 Recommendations:")
            for rec in health_summary["recommendations"]:
                logger.info(f"   - {rec}")
        
        return health_summary
    
    def _get_health_recommendations(self, cred_results: Dict, tool_results: Dict) -> list:
        """Generate health improvement recommendations"""
        recommendations = []
        
        # Credential recommendations
        if cred_results.get("healthy_services", 0) < cred_results.get("total_services", 1):
            recommendations.append("Run 'python scripts/service_health_manager.py --fix-credentials' to repair credential issues")
        
        # Tool discovery recommendations  
        if tool_results.get("status") != "success":
            recommendations.append("Check MCP server health and network connectivity")
        elif tool_results.get("total_tools", 0) < 10:  # Expected minimum tools
            recommendations.append("Some MCP servers may be unreachable - verify service health")
            
        # Server-specific recommendations
        server_health = tool_results.get("server_health", {})
        unhealthy_servers = [name for name, health in server_health.items() 
                           if health.get("status") != "healthy"]
        
        if unhealthy_servers:
            recommendations.append(f"Restart unhealthy MCP servers: {', '.join(unhealthy_servers)}")
        
        return recommendations
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format"""
        from datetime import datetime
        return datetime.utcnow().isoformat() + "Z"

async def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(description="Service Health Manager")
    parser.add_argument("--validate-credentials", action="store_true", 
                       help="Validate service client credentials")
    parser.add_argument("--fix-credentials", action="store_true",
                       help="Attempt to fix credential issues")
    parser.add_argument("--discover-tools", action="store_true",
                       help="Discover and validate MCP tools")
    parser.add_argument("--health-check", action="store_true",
                       help="Perform comprehensive health check")
    parser.add_argument("--json", action="store_true",
                       help="Output results in JSON format")
    
    args = parser.parse_args()
    
    if not any([args.validate_credentials, args.fix_credentials, 
               args.discover_tools, args.health_check]):
        parser.print_help()
        return
    
    manager = ServiceHealthManager()
    
    try:
        if args.health_check:
            results = await manager.comprehensive_health_check()
        elif args.validate_credentials:
            results = await manager.validate_all_credentials()
        elif args.fix_credentials:
            results = await manager.fix_credentials()
        elif args.discover_tools:
            results = await manager.discover_mcp_tools()
        
        if args.json:
            print(json.dumps(results, indent=2))
        
        # Exit with appropriate code
        if results.get("status") in ["success", "completed"]:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Health manager failed: {e}", exc_info=True)
        if args.json:
            print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())