#!/usr/bin/env python3
"""
Example HTTP MCP Tool Server - Weather Service
===============================================

This example demonstrates an HTTP-based MCP server using FastAPI.
This pattern is useful for:
- Remote tool servers (different host/container)
- Multiple concurrent requests
- RESTful tool access
- Integration with existing FastAPI apps

Usage:
    # 1. Start the HTTP MCP server
    python examples/mcp_tools/example_weather_http_server.py
    # Or with uvicorn:
    uvicorn examples.mcp_tools.example_weather_http_server:app --host 0.0.0.0 --port 8090

    # 2. Register with ADEPT
    agentic tool register \\
        --name weather_http \\
        --type mcp \\
        --url http://localhost:8090 \\
        --description "HTTP-based weather service"

    # 3. Test endpoints
    curl http://localhost:8090/tools/list
    curl -X POST http://localhost:8090/tools/call \\
        -H "Content-Type: application/json" \\
        -d '{"name": "get_weather", "arguments": {"city": "Paris"}}'

Requirements:
    pip install fastapi uvicorn httpx
"""

from typing import Dict, Any, List
import logging
import sys
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field


# ==============================================================================
# Logging Setup
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# ==============================================================================
# FastAPI App Setup
# ==============================================================================

app = FastAPI(
    title="Weather MCP Server",
    description="HTTP-based MCP tool server for weather data",
    version="1.0.0"
)


# Add request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming {request.method} request to {request.url.path}")
    logger.debug(f"Headers: {dict(request.headers)}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response


# ==============================================================================
# MCP Protocol Models
# ==============================================================================

class ToolInfo(BaseModel):
    """Tool information for MCP protocol."""
    name: str
    description: str
    inputSchema: Dict[str, Any]


class ToolCallRequest(BaseModel):
    """MCP tool call request."""
    name: str
    arguments: Dict[str, Any]


class ToolCallResponse(BaseModel):
    """MCP tool call response."""
    content: List[Dict[str, Any]]
    isError: bool = False


# ==============================================================================
# Weather Tools Implementation
# ==============================================================================

async def get_weather_impl(city: str, units: str = "celsius") -> Dict[str, Any]:
    """
    Get current weather for a specified city.

    Args:
        city: Name of the city
        units: Temperature units ("celsius" or "fahrenheit")

    Returns:
        Dictionary with weather data
    """
    # Mock weather data
    mock_weather_data = {
        "paris": {"temp_c": 18, "temp_f": 64, "conditions": "partly cloudy", "humidity": 65, "wind": 12},
        "new york": {"temp_c": 22, "temp_f": 72, "conditions": "sunny", "humidity": 55, "wind": 8},
        "tokyo": {"temp_c": 25, "temp_f": 77, "conditions": "clear", "humidity": 70, "wind": 10},
        "london": {"temp_c": 15, "temp_f": 59, "conditions": "rainy", "humidity": 85, "wind": 15},
        "sydney": {"temp_c": 28, "temp_f": 82, "conditions": "sunny", "humidity": 60, "wind": 14},
    }

    city_lower = city.lower()
    data = mock_weather_data.get(city_lower, {
        "temp_c": 20, "temp_f": 68, "conditions": "partly cloudy", "humidity": 60, "wind": 10
    })

    temperature = data["temp_f"] if units == "fahrenheit" else data["temp_c"]

    return {
        "city": city,
        "temperature": temperature,
        "conditions": data["conditions"],
        "humidity": data["humidity"],
        "wind_speed": data["wind"],
        "units": units
    }


async def get_forecast_impl(city: str, days: int = 5) -> Dict[str, Any]:
    """
    Get weather forecast for a specified city.

    Args:
        city: Name of the city
        days: Number of days to forecast (1-7)

    Returns:
        Dictionary with forecast data
    """
    if days < 1 or days > 7:
        return {
            "error": "days parameter must be between 1 and 7",
            "city": city,
            "days": days
        }

    conditions_rotation = ["sunny", "partly cloudy", "cloudy", "rainy", "clear"]

    forecast = []
    for day in range(1, days + 1):
        high = 18 + (day % 5)
        low = 10 + (day % 4)
        conditions = conditions_rotation[(day - 1) % len(conditions_rotation)]

        forecast.append({
            "day": day,
            "high": high,
            "low": low,
            "conditions": conditions
        })

    return {
        "city": city,
        "days": days,
        "forecast": forecast
    }


# ==============================================================================
# MCP Protocol Endpoints
# ==============================================================================

@app.get("/")
async def root():
    """Root endpoint with server information."""
    logger.info("Root endpoint accessed - returning server info")
    return {
        "name": "Weather MCP Server",
        "version": "1.0.0",
        "protocol": "MCP over HTTP",
        "tools": ["get_weather", "get_forecast"],
        "endpoints": {
            "tools_list": "/tools/list",
            "tools_call": "/tools/call"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    logger.info("Health check accessed - status: healthy")
    return {"status": "healthy", "server": "weather-mcp"}


@app.get("/tools/list")
async def list_tools():
    """
    MCP tools/list endpoint.

    Returns list of available tools with their schemas.
    """
    logger.info("Tools list requested")
    tools = [
        ToolInfo(
            name="get_weather",
            description="Get current weather for a specified city",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "Name of the city (e.g., 'Paris', 'New York')"
                    },
                    "units": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "default": "celsius",
                        "description": "Temperature units"
                    }
                },
                "required": ["city"]
            }
        ),
        ToolInfo(
            name="get_forecast",
            description="Get weather forecast for a specified city",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "Name of the city"
                    },
                    "days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 7,
                        "default": 5,
                        "description": "Number of days to forecast"
                    }
                },
                "required": ["city"]
            }
        )
    ]

    logger.info(f"Returning {len(tools)} tools: {[t.name for t in tools]}")
    return {"tools": [tool.dict() for tool in tools]}


@app.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    """
    MCP tools/call endpoint.

    Execute a tool with provided arguments.
    """
    tool_name = request.name
    arguments = request.arguments

    logger.info(f"Tool call requested: {tool_name} with arguments: {arguments}")

    # Route to appropriate tool implementation
    try:
        if tool_name == "get_weather":
            logger.debug(f"Executing get_weather for city={arguments.get('city')}, units={arguments.get('units', 'celsius')}")
            result = await get_weather_impl(
                city=arguments.get("city"),
                units=arguments.get("units", "celsius")
            )
        elif tool_name == "get_forecast":
            logger.debug(f"Executing get_forecast for city={arguments.get('city')}, days={arguments.get('days', 5)}")
            result = await get_forecast_impl(
                city=arguments.get("city"),
                days=arguments.get("days", 5)
            )
        else:
            logger.warning(f"Tool not found: {tool_name}")
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

        logger.info(f"Tool execution successful: {tool_name}")
        logger.debug(f"Tool result: {str(result)[:200]}...")  # Log first 200 chars
        return ToolCallResponse(
            content=[{
                "type": "text",
                "text": str(result)
            }],
            isError=False
        )

    except Exception as e:
        logger.error(f"Tool execution failed: {tool_name}, error: {str(e)}")
        return ToolCallResponse(
            content=[{
                "type": "text",
                "text": f"Error executing tool: {str(e)}"
            }],
            isError=True
        )


# ==============================================================================
# Standalone Execution
# ==============================================================================

def main():
    """Run the HTTP MCP server."""
    print("=" * 80)
    print("Example Weather HTTP MCP Server")
    print("=" * 80)
    print()
    print("Server Status: STARTING")
    print("Protocol: MCP over HTTP")
    print("Port: 8090")
    print()
    print("Available Tools:")
    print("  - get_weather(city, units='celsius')")
    print("  - get_forecast(city, days=5)")
    print()
    print("MCP Endpoints:")
    print("  - GET  http://localhost:8090/tools/list")
    print("  - POST http://localhost:8090/tools/call")
    print()
    print("Registration Example:")
    print("  agentic tool register \\")
    print("    --name weather_http \\")
    print("    --type mcp \\")
    print("    --url http://localhost:8090 \\")
    print("    --description 'HTTP-based weather service'")
    print()
    print("Test Endpoints:")
    print("  curl http://localhost:8090/tools/list")
    print("  curl -X POST http://localhost:8090/tools/call \\")
    print("    -H 'Content-Type: application/json' \\")
    print("    -d '{\"name\": \"get_weather\", \"arguments\": {\"city\": \"Paris\"}}'")
    print()
    print("Server Status: READY")
    print("=" * 80)
    print()

    # Run with uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="info")


if __name__ == "__main__":
    main()
