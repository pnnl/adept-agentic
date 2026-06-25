"""Allowlist Rule Parser and Matcher — generic library module.

Parses .asopb-allowlist.yaml (category-level false positive suppression rules)
and provides a matching API to determine whether a scan finding should be
suppressed based on declarative rules.

The allowlist operates at the CATEGORY level (broad patterns applied before
instance-level compensating controls). Rules are evaluated in order; first
match suppresses the finding.

This module contains codebase-agnostic logic: schema models, YAML parsing,
rule matching, and validation. The integration point in the scan pipeline
calls `matches_finding()` during scoring.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field


# ─── Constants ───────────────────────────────────────────────────────────────

SCHEMA_VERSION = 1
VALID_CATEGORIES = ("ner_pii", "secrets", "trufflehog", "toxicity", "regex")


class AllowlistRule(BaseModel):
    """A single suppression rule within a category."""
    type: Optional[str] = None
    category: Optional[str] = None
    file_patterns: list[str] = Field(default_factory=list)
    pattern: Optional[str] = None
    min_score: Optional[float] = None
    max_entity_length: Optional[int] = None
    reason: str = ""


class AllowlistCategory(BaseModel):
    """A named category containing ordered rules."""
    name: str
    rules: list[AllowlistRule] = Field(default_factory=list)


class Allowlist(BaseModel):
    """Complete parsed allowlist with all categories."""
    schema_version: int = SCHEMA_VERSION
    content_hash: str = ""
    categories: list[AllowlistCategory] = Field(default_factory=list)

    def get_category(self, name: str) -> Optional[AllowlistCategory]:
        for cat in self.categories:
            if cat.name == name:
                return cat
        return None

    @property
    def total_rules(self) -> int:
        return sum(len(cat.rules) for cat in self.categories)


# ─── Parsing ─────────────────────────────────────────────────────────────────


def compute_allowlist_hash(path: Path) -> str:
    """Compute SHA-256 hash of the allowlist file content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_allowlist(path: Path) -> Optional[Allowlist]:
    """Load and parse an allowlist YAML file."""
    if not path.exists():
        return None
    try:
        content_hash = compute_allowlist_hash(path)
        with open(path) as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    categories = []
    for cat_name, rules_data in data.items():
        if not isinstance(rules_data, list):
            continue
        rules = []
        for rule_data in rules_data:
            if not isinstance(rule_data, dict):
                continue
            rules.append(AllowlistRule(**{
                k: v for k, v in rule_data.items()
                if k in AllowlistRule.model_fields
            }))
        categories.append(AllowlistCategory(name=cat_name, rules=rules))

    return Allowlist(
        schema_version=SCHEMA_VERSION,
        content_hash=content_hash,
        categories=categories,
    )


# ─── Validation ──────────────────────────────────────────────────────────────


@dataclass
class ValidationIssue:
    category: str
    rule_index: int
    severity: Literal["ERROR", "WARNING"]
    message: str


def validate_allowlist(allowlist: Allowlist) -> list[ValidationIssue]:
    """Validate allowlist structure and rule consistency."""
    issues = []

    for cat in allowlist.categories:
        if cat.name not in VALID_CATEGORIES:
            issues.append(ValidationIssue(
                cat.name, -1, "WARNING",
                f"Unknown category '{cat.name}' (valid: {', '.join(VALID_CATEGORIES)})"
            ))

        for i, rule in enumerate(cat.rules):
            if not rule.reason:
                issues.append(ValidationIssue(
                    cat.name, i, "ERROR",
                    "Rule missing 'reason' field"
                ))

            if not rule.type and not rule.pattern and not rule.file_patterns and not rule.category:
                issues.append(ValidationIssue(
                    cat.name, i, "ERROR",
                    "Rule has no matching criteria (needs type, pattern, file_patterns, or category)"
                ))

            if rule.min_score is not None and not (0.0 <= rule.min_score <= 1.0):
                issues.append(ValidationIssue(
                    cat.name, i, "ERROR",
                    f"min_score {rule.min_score} out of range [0.0, 1.0]"
                ))

            if rule.max_entity_length is not None and rule.max_entity_length < 1:
                issues.append(ValidationIssue(
                    cat.name, i, "ERROR",
                    f"max_entity_length {rule.max_entity_length} must be >= 1"
                ))

    return issues


# ─── Matching ────────────────────────────────────────────────────────────────


@dataclass
class MatchResult:
    suppressed: bool
    rule_index: int = -1
    category: str = ""
    reason: str = ""
    allowlist_hash: str = ""


def _file_matches_patterns(file_path: str, patterns: list[str]) -> bool:
    """Check if a file path matches any of the glob patterns."""
    basename = Path(file_path).name
    for pattern in patterns:
        if fnmatch.fnmatch(basename, pattern):
            return True
        if fnmatch.fnmatch(file_path, pattern):
            return True
    return False


def matches_finding(
    finding: dict,
    allowlist: Allowlist,
    category_name: Optional[str] = None,
) -> MatchResult:
    """Check if a finding should be suppressed by the allowlist.

    Args:
        finding: Dict with keys like 'type', 'file', 'entity', 'score', 'category'.
        allowlist: Parsed allowlist to match against.
        category_name: If provided, only check rules in this category.
            If None, checks all categories.

    Returns:
        MatchResult indicating whether the finding is suppressed and why.
    """
    finding_type = finding.get("type", "")
    finding_file = finding.get("file", "")
    finding_entity = finding.get("entity", "")
    finding_score = finding.get("score", 0.0)
    finding_category = finding.get("category", "")
    finding_pattern_content = finding.get("content", finding_entity)

    categories_to_check = allowlist.categories
    if category_name:
        cat = allowlist.get_category(category_name)
        categories_to_check = [cat] if cat else []

    for cat in categories_to_check:
        for i, rule in enumerate(cat.rules):
            if not _rule_matches(rule, finding_type, finding_file,
                                 finding_entity, finding_score,
                                 finding_category, finding_pattern_content):
                continue
            return MatchResult(
                suppressed=True,
                rule_index=i,
                category=cat.name,
                reason=rule.reason,
                allowlist_hash=allowlist.content_hash,
            )

    return MatchResult(suppressed=False)


def _rule_matches(
    rule: AllowlistRule,
    finding_type: str,
    finding_file: str,
    finding_entity: str,
    finding_score: float,
    finding_category: str,
    finding_content: str,
) -> bool:
    """Check if a single rule matches a finding. All specified criteria must match."""
    if rule.type and rule.type != finding_type:
        return False

    if rule.category and rule.category != finding_category:
        return False

    if rule.file_patterns and finding_file:
        if not _file_matches_patterns(finding_file, rule.file_patterns):
            return False

    if rule.pattern:
        if rule.pattern not in finding_entity and rule.pattern not in finding_content:
            return False

    if rule.min_score is not None:
        if finding_score < rule.min_score:
            return False

    if rule.max_entity_length is not None:
        if len(finding_entity) > rule.max_entity_length:
            return False

    return True
