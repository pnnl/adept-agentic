def search(query: str) -> str:
    return f"Search results for {query}"

def calculator(expr: str) -> float:
    return eval(expr)

def register_tools(agent):
    agent.tools = [search, calculator]
