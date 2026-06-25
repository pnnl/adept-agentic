import asyncio
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.tools import tool

class SimpleAgent:
    def __init__(self):
        self.tools = []

    async def run(self, query: str):
        return f"Response to: {query}"

    def register_tools(self):
        self.tools = ["search", "calculator"]

agent = SimpleAgent()
agent.register_tools()
