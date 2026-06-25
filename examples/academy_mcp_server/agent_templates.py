"""
Academy MCP Server — Agent Templates

Pre-built Academy agent classes for integration testing and demos.
All agents use the @action decorator and subclass academy.agent.Agent.
"""

import math
from academy.agent import Agent, action


class EchoAgent(Agent):
    """Simple echo agent for integration testing.

    Actions:
        echo(message: str) -> dict: Echo back the message
        get_call_count() -> dict: Return total number of echo calls
    """

    def __init__(self):
        super().__init__()
        self._call_count = 0

    async def agent_on_startup(self) -> None:
        pass

    @action
    async def echo(self, message: str = "hello") -> dict:
        """Echo back the provided message."""
        self._call_count += 1
        return {"echo": message, "call_count": self._call_count}

    @action
    async def get_call_count(self) -> dict:
        """Return the total number of echo calls."""
        return {"call_count": self._call_count}


class CounterAgent(Agent):
    """Stateful counter agent for demonstrating persistent state.

    Actions:
        increment(value: int) -> dict: Add value to counter
        decrement(value: int) -> dict: Subtract value from counter
        get_count() -> dict: Return current counter value
        reset() -> dict: Reset counter to initial value
    """

    def __init__(self, initial_value: int = 0):
        super().__init__()
        self._initial_value = initial_value
        self._count = initial_value

    async def agent_on_startup(self) -> None:
        pass

    @action
    async def increment(self, value: int = 1) -> dict:
        """Increment the counter by the given value."""
        self._count += value
        return {"count": self._count, "delta": value}

    @action
    async def decrement(self, value: int = 1) -> dict:
        """Decrement the counter by the given value."""
        self._count -= value
        return {"count": self._count, "delta": -value}

    @action
    async def get_count(self) -> dict:
        """Return the current counter value."""
        return {"count": self._count}

    @action
    async def reset(self) -> dict:
        """Reset the counter to its initial value."""
        old_count = self._count
        self._count = self._initial_value
        return {"count": self._count, "previous": old_count}


class ComputeAgent(Agent):
    """Scientific computation agent for demonstrating compute capabilities.

    Actions:
        factorial(n: int) -> dict: Compute n!
        fibonacci(n: int) -> dict: Compute nth Fibonacci number
        is_prime(n: int) -> dict: Check if n is prime
        get_computation_count() -> dict: Return total computations performed
    """

    def __init__(self):
        super().__init__()
        self._computation_count = 0

    async def agent_on_startup(self) -> None:
        pass

    @action
    async def factorial(self, n: int = 7) -> dict:
        """Compute the factorial of n."""
        if n < 0:
            return {"error": "n must be non-negative", "n": n}
        self._computation_count += 1
        result = math.factorial(n)
        return {"factorial": result, "n": n}

    @action
    async def fibonacci(self, n: int = 10) -> dict:
        """Compute the nth Fibonacci number (0-indexed)."""
        if n < 0:
            return {"error": "n must be non-negative", "n": n}
        self._computation_count += 1
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
        return {"fibonacci": a, "n": n}

    @action
    async def is_prime(self, n: int = 17) -> dict:
        """Check whether n is a prime number."""
        if n < 2:
            self._computation_count += 1
            return {"is_prime": False, "n": n}
        self._computation_count += 1
        for i in range(2, int(math.isqrt(n)) + 1):
            if n % i == 0:
                return {"is_prime": False, "n": n, "factor": i}
        return {"is_prime": True, "n": n}

    @action
    async def get_computation_count(self) -> dict:
        """Return the total number of computations performed."""
        return {"computation_count": self._computation_count}


# Map of agent type names to classes (used by manager_registry)
AGENT_TEMPLATES = {
    "echo": EchoAgent,
    "counter": CounterAgent,
    "compute": ComputeAgent,
}
