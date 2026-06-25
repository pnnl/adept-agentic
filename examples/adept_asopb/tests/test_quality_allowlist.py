"""Unit tests for asopb.quality.allowlist library module."""

import tempfile
from pathlib import Path

import pytest

from asopb.quality.allowlist import (
    SCHEMA_VERSION,
    Allowlist,
    AllowlistCategory,
    AllowlistRule,
    MatchResult,
    ValidationIssue,
    compute_allowlist_hash,
    load_allowlist,
    matches_finding,
    validate_allowlist,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


SAMPLE_ALLOWLIST_YAML = """\
ner_pii:
  - type: "PII:PASSWORD"
    file_patterns: ["*.py", "*.sh"]
    reason: "DeBERTa cannot distinguish code syntax from passwords"
  - type: "PII:IBAN"
    reason: "Zero true positives — model misidentifies paths and hex strings"
  - type: "PII:USERNAME"
    max_entity_length: 4
    reason: "Model fragments code identifiers into false username detections"
  - type: "PII:EMAIL"
    pattern: "@example."
    reason: "RFC 2606 reserved example domains"

secrets:
  - pattern: "secretName:"
    reason: "Kubernetes secret resource name reference"
  - pattern: "admin:password@postgres"
    reason: "Local-only Docker Compose default"

toxicity:
  - file_patterns: ["*.py", "*.sh"]
    min_score: 0.95
    reason: "Technical terms in code"

regex:
  - category: "institutional"
    file_patterns: ["LICENSE*", "pyproject.toml"]
    reason: "Required for DOE open-source release compliance"
"""


@pytest.fixture
def sample_allowlist_path():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(SAMPLE_ALLOWLIST_YAML)
        f.flush()
        yield Path(f.name)


@pytest.fixture
def sample_allowlist(sample_allowlist_path):
    return load_allowlist(sample_allowlist_path)


# ─── Loading ─────────────────────────────────────────────────────────────────


class TestLoading:
    def test_load_valid_file(self, sample_allowlist):
        assert sample_allowlist is not None
        assert len(sample_allowlist.categories) == 4

    def test_load_nonexistent_returns_none(self):
        result = load_allowlist(Path("/nonexistent/allowlist.yaml"))
        assert result is None

    def test_load_malformed_yaml_returns_none(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(": : : [invalid yaml")
            f.flush()
            result = load_allowlist(Path(f.name))
            assert result is None

    def test_load_non_dict_returns_none(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("- just\n- a\n- list\n")
            f.flush()
            result = load_allowlist(Path(f.name))
            assert result is None

    def test_category_names_preserved(self, sample_allowlist):
        names = [c.name for c in sample_allowlist.categories]
        assert "ner_pii" in names
        assert "secrets" in names
        assert "toxicity" in names
        assert "regex" in names

    def test_rule_counts(self, sample_allowlist):
        ner = sample_allowlist.get_category("ner_pii")
        assert ner is not None
        assert len(ner.rules) == 4

        secrets = sample_allowlist.get_category("secrets")
        assert secrets is not None
        assert len(secrets.rules) == 2

    def test_total_rules(self, sample_allowlist):
        assert sample_allowlist.total_rules == 8

    def test_rule_fields_parsed(self, sample_allowlist):
        ner = sample_allowlist.get_category("ner_pii")
        rule = ner.rules[0]
        assert rule.type == "PII:PASSWORD"
        assert rule.file_patterns == ["*.py", "*.sh"]
        assert "DeBERTa" in rule.reason

    def test_get_nonexistent_category(self, sample_allowlist):
        assert sample_allowlist.get_category("nonexistent") is None

    def test_schema_version_set(self, sample_allowlist):
        assert sample_allowlist.schema_version == SCHEMA_VERSION

    def test_content_hash_computed(self, sample_allowlist):
        assert sample_allowlist.content_hash != ""
        assert len(sample_allowlist.content_hash) == 64

    def test_content_hash_deterministic(self, sample_allowlist_path):
        al1 = load_allowlist(sample_allowlist_path)
        al2 = load_allowlist(sample_allowlist_path)
        assert al1.content_hash == al2.content_hash

    def test_content_hash_changes_with_content(self, sample_allowlist_path):
        al1 = load_allowlist(sample_allowlist_path)
        with open(sample_allowlist_path, "a") as f:
            f.write("\n# extra comment\n")
        al2 = load_allowlist(sample_allowlist_path)
        assert al1.content_hash != al2.content_hash

    def test_compute_allowlist_hash(self, sample_allowlist_path):
        h = compute_allowlist_hash(sample_allowlist_path)
        assert len(h) == 64
        al = load_allowlist(sample_allowlist_path)
        assert al.content_hash == h


# ─── Validation ──────────────────────────────────────────────────────────────


class TestValidation:
    def test_valid_allowlist_no_errors(self, sample_allowlist):
        issues = validate_allowlist(sample_allowlist)
        errors = [i for i in issues if i.severity == "ERROR"]
        assert len(errors) == 0

    def test_unknown_category_warns(self):
        allowlist = Allowlist(categories=[
            AllowlistCategory(name="unknown_category", rules=[
                AllowlistRule(type="X", reason="test")
            ])
        ])
        issues = validate_allowlist(allowlist)
        warnings = [i for i in issues if i.severity == "WARNING"]
        assert len(warnings) == 1
        assert "Unknown category" in warnings[0].message

    def test_missing_reason_errors(self):
        allowlist = Allowlist(categories=[
            AllowlistCategory(name="ner_pii", rules=[
                AllowlistRule(type="PII:PASSWORD", reason="")
            ])
        ])
        issues = validate_allowlist(allowlist)
        errors = [i for i in issues if i.severity == "ERROR"]
        assert any("missing 'reason'" in e.message for e in errors)

    def test_no_criteria_errors(self):
        allowlist = Allowlist(categories=[
            AllowlistCategory(name="secrets", rules=[
                AllowlistRule(reason="no matching criteria")
            ])
        ])
        issues = validate_allowlist(allowlist)
        errors = [i for i in issues if i.severity == "ERROR"]
        assert any("no matching criteria" in e.message for e in errors)

    def test_invalid_min_score_errors(self):
        allowlist = Allowlist(categories=[
            AllowlistCategory(name="toxicity", rules=[
                AllowlistRule(min_score=1.5, file_patterns=["*.py"], reason="bad")
            ])
        ])
        issues = validate_allowlist(allowlist)
        errors = [i for i in issues if i.severity == "ERROR"]
        assert any("out of range" in e.message for e in errors)

    def test_invalid_max_entity_length_errors(self):
        allowlist = Allowlist(categories=[
            AllowlistCategory(name="ner_pii", rules=[
                AllowlistRule(type="PII:USERNAME", max_entity_length=0, reason="bad")
            ])
        ])
        issues = validate_allowlist(allowlist)
        errors = [i for i in issues if i.severity == "ERROR"]
        assert any("must be >= 1" in e.message for e in errors)


# ─── Matching ────────────────────────────────────────────────────────────────


class TestMatching:
    def test_type_match(self, sample_allowlist):
        finding = {"type": "PII:IBAN", "file": "src/foo.py", "entity": "DE89370400440532013000"}
        result = matches_finding(finding, sample_allowlist)
        assert result.suppressed is True
        assert result.category == "ner_pii"
        assert "misidentifies" in result.reason

    def test_type_plus_file_pattern_match(self, sample_allowlist):
        finding = {"type": "PII:PASSWORD", "file": "src/module.py", "entity": "x" * 20}
        result = matches_finding(finding, sample_allowlist)
        assert result.suppressed is True

    def test_type_plus_file_pattern_no_match(self, sample_allowlist):
        finding = {"type": "PII:PASSWORD", "file": "data/secrets.csv", "entity": "x" * 20}
        result = matches_finding(finding, sample_allowlist)
        assert result.suppressed is False

    def test_pattern_match(self, sample_allowlist):
        finding = {"type": "", "file": "helm/values.yaml", "entity": "secretName: my-secret"}
        result = matches_finding(finding, sample_allowlist, category_name="secrets")
        assert result.suppressed is True
        assert "Kubernetes" in result.reason

    def test_pattern_in_content_field(self, sample_allowlist):
        finding = {"type": "", "file": "docker-compose.yaml",
                   "entity": "POSTGRES_URL", "content": "admin:password@postgres:5432"}
        result = matches_finding(finding, sample_allowlist, category_name="secrets")
        assert result.suppressed is True

    def test_max_entity_length_match(self, sample_allowlist):
        finding = {"type": "PII:USERNAME", "file": "src/x.py", "entity": "bob"}
        result = matches_finding(finding, sample_allowlist)
        assert result.suppressed is True

    def test_max_entity_length_no_match(self, sample_allowlist):
        finding = {"type": "PII:USERNAME", "file": "src/x.py", "entity": "paulrigor"}
        result = matches_finding(finding, sample_allowlist)
        assert result.suppressed is False

    def test_min_score_match(self, sample_allowlist):
        finding = {"type": "", "file": "src/module.py", "entity": "kill process",
                   "score": 0.97, "content": "kill process"}
        result = matches_finding(finding, sample_allowlist, category_name="toxicity")
        assert result.suppressed is True

    def test_min_score_below_threshold(self, sample_allowlist):
        finding = {"type": "", "file": "src/module.py", "entity": "kill process",
                   "score": 0.80, "content": "kill process"}
        result = matches_finding(finding, sample_allowlist, category_name="toxicity")
        assert result.suppressed is False

    def test_category_field_match(self, sample_allowlist):
        finding = {"type": "", "file": "LICENSE", "entity": "PNNL",
                   "category": "institutional"}
        result = matches_finding(finding, sample_allowlist, category_name="regex")
        assert result.suppressed is True

    def test_category_field_no_match(self, sample_allowlist):
        finding = {"type": "", "file": "LICENSE", "entity": "PNNL",
                   "category": "credential"}
        result = matches_finding(finding, sample_allowlist, category_name="regex")
        assert result.suppressed is False

    def test_email_pattern_match(self, sample_allowlist):
        finding = {"type": "PII:EMAIL", "file": "src/test.py",
                   "entity": "user@example.org"}
        result = matches_finding(finding, sample_allowlist)
        assert result.suppressed is True
        assert "RFC 2606" in result.reason

    def test_no_match_returns_not_suppressed(self, sample_allowlist):
        finding = {"type": "PII:CREDIT_CARD", "file": "src/billing.py",
                   "entity": "4111111111111111"}
        result = matches_finding(finding, sample_allowlist)
        assert result.suppressed is False
        assert result.rule_index == -1

    def test_match_result_includes_allowlist_hash(self, sample_allowlist):
        finding = {"type": "PII:IBAN", "file": "src/foo.py", "entity": "DE89370400440532013000"}
        result = matches_finding(finding, sample_allowlist)
        assert result.suppressed is True
        assert result.allowlist_hash == sample_allowlist.content_hash
        assert len(result.allowlist_hash) == 64

    def test_no_match_has_empty_hash(self, sample_allowlist):
        finding = {"type": "PII:CREDIT_CARD", "file": "src/billing.py",
                   "entity": "4111111111111111"}
        result = matches_finding(finding, sample_allowlist)
        assert result.suppressed is False
        assert result.allowlist_hash == ""

    def test_first_matching_rule_wins(self, sample_allowlist):
        finding = {"type": "PII:PASSWORD", "file": "src/app.py",
                   "entity": "admin:password@postgres"}
        result = matches_finding(finding, sample_allowlist)
        assert result.suppressed is True
        assert result.category == "ner_pii"
        assert result.rule_index == 0

    def test_category_name_filter(self, sample_allowlist):
        finding = {"type": "PII:IBAN", "file": "src/x.py", "entity": "DE89"}
        result = matches_finding(finding, sample_allowlist, category_name="secrets")
        assert result.suppressed is False

    def test_empty_allowlist_no_match(self):
        finding = {"type": "PII:PASSWORD", "file": "x.py", "entity": "secret"}
        result = matches_finding(finding, Allowlist())
        assert result.suppressed is False


# ─── Real File Loading ───────────────────────────────────────────────────────


class TestRealAllowlist:
    """Test against the actual .asopb-allowlist.yaml in the repo."""

    @pytest.fixture
    def real_allowlist(self):
        real_path = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "release" / ".asopb-allowlist.yaml"
        if not real_path.exists():
            pytest.skip(f"Real allowlist not found at {real_path}")
        return load_allowlist(real_path)

    def test_real_allowlist_loads(self, real_allowlist):
        assert real_allowlist is not None
        assert real_allowlist.total_rules > 0

    def test_real_allowlist_validates(self, real_allowlist):
        issues = validate_allowlist(real_allowlist)
        errors = [i for i in issues if i.severity == "ERROR"]
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_real_allowlist_suppresses_password_on_python(self, real_allowlist):
        finding = {"type": "PII:PASSWORD", "file": "src/core/auth.py",
                   "entity": "os.getenv('DB_PASSWORD')"}
        result = matches_finding(finding, real_allowlist, category_name="ner_pii")
        assert result.suppressed is True

    def test_real_allowlist_suppresses_iban(self, real_allowlist):
        finding = {"type": "PII:IBAN", "file": "src/utils.py",
                   "entity": "/var/lib/docker/containerd"}
        result = matches_finding(finding, real_allowlist, category_name="ner_pii")
        assert result.suppressed is True
