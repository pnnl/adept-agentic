#!/usr/bin/env python3
"""
Example MCP Tool Server - Weather Service
==========================================

This is a minimal example demonstrating how to create an external MCP tool
server for dynamic registration with the ADEPT framework.

Purpose:
- Shows the basic structure of an MCP tool server
- Demonstrates tool registration via ADEPT CLI or API
- Provides a template for creating custom external tools

Usage:
    # 1. Start the MCP server
    python examples/mcp_tools/example_weather_mcp_server.py

    # 2. Register with ADEPT (via CLI)
    agentic tool register \\
        --name weather_service \\
        --type mcp \\
        --url http://localhost:8090 \\
        --description "Get current weather for a city"

    # 3. Use in agent workflows
    # The agent will now have access to the get_weather tool

Requirements:
    pip install mcp httpx
"""

import asyncio
import json
from typing import Dict, Any

# MCP imports
try:
    from mcp import Mcpython3
    from mcp.server.stdio import stdio_server
    mcp = Mcpython3("example-weather-server", "1.0.0")
except ImportError:
    print("ERROR: mcp package not installed. Install with: pip install mcp")
    exit(1)


@mcp.tool()
async def get_weather(city: str, units: str = "celsius") -> Dict[str, Any]:
    """
    Get current weather for a specified city.

    This is a mock implementation for demonstration purposes.
    In production, you would call a real weather API (OpenWeatherMap, WeatherAPI, etc.).

    Args:
        city: Name of the city (e.g., "Paris", "New York", "Tokyo")
        units: Temperature units ("celsius" or "fahrenheit")

    Returns:
        Dictionary containing weather information:
        - city: City name
        - temperature: Current temperature
        - conditions: Weather conditions
        - humidity: Humidity percentage
        - wind_speed: Wind speed
        - units: Temperature units used

    Example:
        >>> weather = await get_weather("Paris")
        >>> print(weather)
        {
            "city": "Paris",
            "temperature": 18,
            "conditions": "partly cloudy",
            "humidity": 65,
            "wind_speed": 12,
            "units": "celsius"
        }
    """
    # Mock weather data (in production, call real weather API)
    mock_weather_data = {
        "paris": {"temp_c": 18, "temp_f": 64, "conditions": "partly cloudy", "humidity": 65, "wind": 12},
        "new york": {"temp_c": 22, "temp_f": 72, "conditions": "sunny", "humidity": 55, "wind": 8},
        "tokyo": {"temp_c": 25, "temp_f": 77, "conditions": "clear", "humidity": 70, "wind": 10},
        "london": {"temp_c": 15, "temp_f": 59, "conditions": "rainy", "humidity": 85, "wind": 15},
        "sydney": {"temp_c": 28, "temp_f": 82, "conditions": "sunny", "humidity": 60, "wind": 14},
    }

    # Normalize city name for lookup
    city_lower = city.lower()

    # Get weather data (use default if city not in mock data)
    if city_lower in mock_weather_data:
        data = mock_weather_data[city_lower]
    else:
        # Default weather for unknown cities
        data = {"temp_c": 20, "temp_f": 68, "conditions": "partly cloudy", "humidity": 60, "wind": 10}

    # Select temperature based on units
    temperature = data["temp_f"] if units == "fahrenheit" else data["temp_c"]

    return {
        "city": city,
        "temperature": temperature,
        "conditions": data["conditions"],
        "humidity": data["humidity"],
        "wind_speed": data["wind"],
        "units": units
    }


@mcp.tool()
async def get_forecast(city: str, days: int = 5) -> Dict[str, Any]:
    """
    Get weather forecast for a specified city.

    This is a mock implementation for demonstration purposes.

    Args:
        city: Name of the city
        days: Number of days to forecast (1-7)

    Returns:
        Dictionary containing forecast information:
        - city: City name
        - forecast: List of daily forecasts
        - days: Number of days forecasted

    Example:
        >>> forecast = await get_forecast("Paris", days=3)
        >>> print(forecast)
        {
            "city": "Paris",
            "days": 3,
            "forecast": [
                {"day": 1, "high": 20, "low": 12, "conditions": "sunny"},
                {"day": 2, "high": 18, "low": 11, "conditions": "cloudy"},
                {"day": 3, "high": 19, "low": 13, "conditions": "partly cloudy"}
            ]
        }
    """
    # Validate days parameter
    if days < 1 or days > 7:
        return {
            "error": "days parameter must be between 1 and 7",
            "city": city,
            "days": days
        }

    # Mock forecast data
    conditions_rotation = ["sunny", "partly cloudy", "cloudy", "rainy", "clear"]

    forecast = []
    for day in range(1, days + 1):
        # Generate mock forecast with some variation
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


async def main():
    """
    Run the MCP server.

    This server exposes two tools:
    - get_weather: Get current weather for a city
    - get_forecast: Get weather forecast for a city

    The server uses stdio transport for communication with the ADEPT framework.
    """
    print("=" * 80)
    print("Example Weather MCP Server")
    print("=" * 80)
    print()
    print("Server Status: STARTING")
    print("Protocol: MCP (Model Context Protocol)")
    print("Transport: stdio")
    print()
    print("Available Tools:")
    print("  - get_weather(city, units='celsius')")
    print("  - get_forecast(city, days=5)")
    print()
    print("Registration Example:")
    print("  agentic tool register \\")
    print("    --name weather_service \\")
    print("    --type mcp \\")
    print("    --url stdio:python examples/mcp_tools/example_weather_mcp_server.py \\")
    print("    --description 'Get weather data for any city'")
    print()
    print("Server Status: READY (listening for MCP messages)")
    print("=" * 80)
    print()

    # Run MCP server with stdio transport
    async with stdio_server() as (read_stream, write_stream):
        await mcp.run(
            read_stream,
            write_stream,
            mcp.create_initialization_options()
        )


if __name__ == "__main__":
    # Run the server
    asyncio.run(main())
