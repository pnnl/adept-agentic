"""Unit tests for asopb.quality.compensating_controls library module."""

import hashlib
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from asopb.quality.compensating_controls import (
    SCHEMA_VERSION,
    CompensatingControlFingerprint,
    ControlManifest,
    LineRange,
    ValidationResult,
    compute_file_sha256,
    compute_fingerprint_hash,
    load_manifest,
    next_control_id,
    save_manifest,
    validate_all,
    validate_control,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_repo():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        src_file = root / "src" / "module.py"
        src_file.parent.mkdir(parents=True)
        src_file.write_text("SECRET_PATH = '/etc/secrets'\n")
        yield root


@pytest.fixture
def sample_control(tmp_repo):
    src_file = tmp_repo / "src" / "module.py"
    file_hash = compute_file_sha256(src_file)
    fp_hash = compute_fingerprint_hash("src/module.py", "1-1", "SECRET_PATH")
    return CompensatingControlFingerprint(
        control_id="D5-001",
        domain="D5",
        rule_description="Path constant, not a secret",
        file_path="src/module.py",
        location=LineRange(start=1, end=1),
        entity_pattern="SECRET_PATH",
        justification="Path constant for secret file lookup, not a secret itself",
        file_sha256=file_hash,
        fingerprint_hash=fp_hash,
        accepted_by="tester",
    )


# ─── Hash Computation ─────────────────────────────────────────────────────────


class TestHashComputation:
    def test_file_sha256_deterministic(self, tmp_repo):
        f = tmp_repo / "src" / "module.py"
        h1 = compute_file_sha256(f)
        h2 = compute_file_sha256(f)
        assert h1 == h2
        assert len(h1) == 64

    def test_file_sha256_changes_with_content(self, tmp_repo):
        f = tmp_repo / "src" / "module.py"
        h1 = compute_file_sha256(f)
        f.write_text("MODIFIED = True\n")
        h2 = compute_file_sha256(f)
        assert h1 != h2

    def test_fingerprint_hash_deterministic(self):
        h1 = compute_fingerprint_hash("file.py", "1-5", "pattern")
        h2 = compute_fingerprint_hash("file.py", "1-5", "pattern")
        assert h1 == h2

    def test_fingerprint_hash_varies_with_inputs(self):
        h1 = compute_fingerprint_hash("file.py", "1-5", "pattern_a")
        h2 = compute_fingerprint_hash("file.py", "1-5", "pattern_b")
        assert h1 != h2

    def test_fingerprint_hash_is_sha256(self):
        h = compute_fingerprint_hash("file.py", "10-20", "entity")
        expected = hashlib.sha256(f"{SCHEMA_VERSION}|file.py|10-20|entity".encode()).hexdigest()
        assert h == expected


# ─── Pydantic Models ─────────────────────────────────────────────────────────


class TestPydanticModels:
    def test_line_range_str(self):
        lr = LineRange(start=10, end=20)
        assert str(lr) == "10-20"

    def test_control_defaults(self):
        ctrl = CompensatingControlFingerprint(
            control_id="D5-001",
            domain="D5",
            rule_description="test",
            file_path="src/x.py",
            location=LineRange(start=1, end=1),
            entity_pattern="ENTITY",
            justification="test justification",
            file_sha256="a" * 64,
            fingerprint_hash="b" * 64,
        )
        assert ctrl.status == "active"
        assert ctrl.version == SCHEMA_VERSION
        assert ctrl.accepted_date == date.today()
        assert ctrl.expiration_date == date.today() + timedelta(days=90)

    def test_control_domain_validation(self):
        with pytest.raises(Exception):
            CompensatingControlFingerprint(
                control_id="X1-001",
                domain="X1",
                rule_description="bad",
                file_path="x.py",
                location="1",
                entity_pattern="e",
                justification="j",
                file_sha256="a" * 64,
                fingerprint_hash="b" * 64,
            )

    def test_manifest_serialization(self, sample_control):
        manifest = ControlManifest(controls=[sample_control])
        data = manifest.model_dump(mode="json")
        restored = ControlManifest.model_validate(data)
        assert len(restored.controls) == 1
        assert restored.controls[0].control_id == "D5-001"

    def test_manifest_empty(self):
        manifest = ControlManifest()
        assert manifest.controls == []
        assert manifest.schema_version == SCHEMA_VERSION

    def test_control_with_string_location(self):
        ctrl = CompensatingControlFingerprint(
            control_id="D7-001",
            domain="D7",
            rule_description="category",
            file_path="glob:*.py",
            location="category-level",
            entity_pattern="pattern",
            justification="category suppression",
            file_sha256="category-level-no-single-file",
            fingerprint_hash="c" * 64,
        )
        assert ctrl.location == "category-level"


# ─── Validation ──────────────────────────────────────────────────────────────


class TestValidation:
    def test_active_control_passes(self, tmp_repo, sample_control):
        result = validate_control(sample_control, tmp_repo)
        assert result.status == "active"
        assert result.severity == "OK"

    def test_file_deleted_invalidates(self, tmp_repo, sample_control):
        (tmp_repo / "src" / "module.py").unlink()
        result = validate_control(sample_control, tmp_repo)
        assert result.status == "invalidated"
        assert result.severity == "CRITICAL"
        assert "no longer exists" in result.reason

    def test_file_modified_marks_stale(self, tmp_repo, sample_control):
        (tmp_repo / "src" / "module.py").write_text("CHANGED = True\n")
        result = validate_control(sample_control, tmp_repo)
        assert result.status == "stale"
        assert result.severity == "CRITICAL"
        assert "hash mismatch" in result.reason

    def test_expired_control_warns(self, tmp_repo, sample_control):
        sample_control.expiration_date = date.today() - timedelta(days=1)
        result = validate_control(sample_control, tmp_repo)
        assert result.status == "expired"
        assert result.severity == "WARNING"

    def test_entity_moved_from_location(self, tmp_repo, sample_control):
        src_file = tmp_repo / "src" / "module.py"
        src_file.write_text("OTHER_THING = 'value'\nSECRET_PATH = '/etc/secrets'\n")
        sample_control.file_sha256 = compute_file_sha256(src_file)
        sample_control.location = LineRange(start=1, end=1)
        result = validate_control(sample_control, tmp_repo)
        assert result.status == "invalidated"
        assert "no longer found" in result.reason

    def test_string_location_skips_line_check(self, tmp_repo, sample_control):
        sample_control.location = "category-level"
        result = validate_control(sample_control, tmp_repo)
        assert result.status == "active"

    def test_validate_all_empty(self):
        with tempfile.TemporaryDirectory() as d:
            manifest_path = Path(d) / "manifest.json"
            results = validate_all(manifest_path, Path(d))
            assert results == []


# ─── ID Generation ───────────────────────────────────────────────────────────


class TestIDGeneration:
    def test_first_id_in_domain(self):
        manifest = ControlManifest()
        assert next_control_id(manifest, "D5") == "D5-001"

    def test_sequential_ids(self, sample_control):
        manifest = ControlManifest(controls=[sample_control])
        assert next_control_id(manifest, "D5") == "D5-002"

    def test_ids_per_domain_independent(self, sample_control):
        manifest = ControlManifest(controls=[sample_control])
        assert next_control_id(manifest, "D7") == "D7-001"


# ─── Manifest I/O ───────────────────────────────────────────────────────────


class TestManifestIO:
    def test_save_and_load(self, sample_control):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "manifest.json"
            manifest = ControlManifest(controls=[sample_control])
            save_manifest(manifest, path)
            loaded = load_manifest(path)
            assert loaded is not None
            assert len(loaded.controls) == 1
            assert loaded.controls[0].control_id == "D5-001"

    def test_load_nonexistent_returns_none(self):
        result = load_manifest(Path("/nonexistent/manifest.json"))
        assert result is None

    def test_load_malformed_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "manifest.json"
            path.write_text("not json")
            result = load_manifest(path)
            assert result is None

    def test_save_creates_parent_dirs(self, sample_control):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "deep" / "nested" / "manifest.json"
            manifest = ControlManifest(controls=[sample_control])
            save_manifest(manifest, path)
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["schema_version"] == SCHEMA_VERSION
