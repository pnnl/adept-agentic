"""
Retention policy parser for session management.

Parses retention policy strings into days for expiration logic.
Supports formats: indefinite, Xd (days), Xm (months), Xy (years)

Examples:
    >>> from retention_policy import RetentionPolicy
    >>> RetentionPolicy.parse("indefinite")
    -1
    >>> RetentionPolicy.parse("30d")
    30
    >>> RetentionPolicy.parse("3m")
    90
    >>> RetentionPolicy.parse("1y")
    365
"""

import re
from typing import Optional
from datetime import timedelta


class RetentionPolicyError(ValueError):
    """Raised when retention policy string is invalid."""

    pass


class RetentionPolicy:
    """
    Parses and validates retention policy strings.

    Supported formats:
    - "indefinite" or "-1": Never delete
    - "30d": 30 days
    - "3m": 3 months (90 days)
    - "1y": 1 year (365 days)
    """

    # Regex pattern for time-based policies
    POLICY_PATTERN = re.compile(r"^(\d+)([dmy])$")

    # Conversion factors
    DAYS_PER_MONTH = 30
    DAYS_PER_YEAR = 365

    @staticmethod
    def parse(policy_str: str) -> int:
        """
        Parse retention policy string to days.

        Args:
            policy_str: Policy string (e.g., "indefinite", "30d", "3m", "1y")

        Returns:
            Number of days (-1 for indefinite retention)

        Raises:
            RetentionPolicyError: If policy string is invalid

        Examples:
            >>> RetentionPolicy.parse("indefinite")
            -1
            >>> RetentionPolicy.parse("-1")
            -1
            >>> RetentionPolicy.parse("30d")
            30
            >>> RetentionPolicy.parse("3m")
            90
            >>> RetentionPolicy.parse("1y")
            365
        """
        if not isinstance(policy_str, str):
            raise RetentionPolicyError(
                f"Policy must be string, got {type(policy_str).__name__}"
            )

        policy_str = policy_str.strip().lower()

        # Handle indefinite retention
        if policy_str in ("indefinite", "-1"):
            return -1

        # Handle time-based retention
        match = RetentionPolicy.POLICY_PATTERN.match(policy_str)
        if not match:
            raise RetentionPolicyError(
                f"Invalid retention policy format: '{policy_str}'. "
                f"Expected 'indefinite', '-1', or format like '30d', '3m', '1y'"
            )

        value = int(match.group(1))
        unit = match.group(2)

        if unit == "d":
            return value
        elif unit == "m":
            return value * RetentionPolicy.DAYS_PER_MONTH
        elif unit == "y":
            return value * RetentionPolicy.DAYS_PER_YEAR

        # Should never reach here due to regex
        raise RetentionPolicyError(f"Unknown unit: {unit}")

    @staticmethod
    def to_timedelta(policy_str: str) -> Optional[timedelta]:
        """
        Convert policy string to timedelta object.

        Args:
            policy_str: Policy string

        Returns:
            timedelta object, or None for indefinite retention

        Examples:
            >>> RetentionPolicy.to_timedelta("30d")
            datetime.timedelta(days=30)
            >>> RetentionPolicy.to_timedelta("indefinite")
            None
        """
        days = RetentionPolicy.parse(policy_str)
        if days == -1:
            return None
        return timedelta(days=days)

    @staticmethod
    def validate(policy_str: str) -> bool:
        """
        Validate policy string without raising exception.

        Args:
            policy_str: Policy string to validate

        Returns:
            True if valid, False otherwise

        Examples:
            >>> RetentionPolicy.validate("30d")
            True
            >>> RetentionPolicy.validate("invalid")
            False
        """
        try:
            RetentionPolicy.parse(policy_str)
            return True
        except RetentionPolicyError:
            return False

    @staticmethod
    def format(days: int) -> str:
        """
        Format days back to policy string (best representation).

        Args:
            days: Number of days (-1 for indefinite)

        Returns:
            Formatted policy string

        Examples:
            >>> RetentionPolicy.format(-1)
            'indefinite'
            >>> RetentionPolicy.format(30)
            '30d'
            >>> RetentionPolicy.format(90)
            '3m'
            >>> RetentionPolicy.format(365)
            '1y'
        """
        if days == -1:
            return "indefinite"

        # Prefer years if exact multiple
        if days % RetentionPolicy.DAYS_PER_YEAR == 0:
            return f"{days // RetentionPolicy.DAYS_PER_YEAR}y"

        # Prefer months if exact multiple
        if days % RetentionPolicy.DAYS_PER_MONTH == 0:
            return f"{days // RetentionPolicy.DAYS_PER_MONTH}m"

        # Otherwise use days
        return f"{days}d"
