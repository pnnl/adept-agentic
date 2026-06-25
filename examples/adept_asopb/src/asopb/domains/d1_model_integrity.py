"""
D1: Model Integrity Domain Evaluator

Evaluates the integrity, safety, and traceability of foundation models
used in agentic systems. Assesses model provenance, deployment controls,
and runtime tampering protection.

Controls:
  D1.1: Model source provenance (is model origin verifiable?)
  D1.2: Model code hash verification (bit-for-bit integrity)
  D1.3: Model quantization/distillation controls (is distillation traced?)
  D1.4: Model deployment signing (is model deployment cryptographically signed?)
  D1.5: Runtime model patching control (can models be modified post-deploy?)
"""

from __future__ import annotations

import re
from typing import Optional

from asopb.config import EvalConfig
from asopb.models import (
    ControlDefinition,
    ControlEvidence,
    ControlScore,
    ControlStatus,
    EvidenceSource,
    EvidenceTier,
    ScanFinding,
    ScanResult,
    Severity,
)

from .base import DomainEvaluator


class D1ModelIntegrityEvaluator(DomainEvaluator):
    """Model Integrity domain evaluator."""

    domain_id = "D1"
    domain_name = "Foundation Model Integrity"
    weight = 1.5
    skill_file = "d1_model_integrity.md"

    def define_controls(self) -> list[ControlDefinition]:
        """Define D1 controls for model integrity."""
        return [
            ControlDefinition(
                control_id="D1.1",
                domain_id="D1",
                name="Model Source Provenance",
                description=(
                    "Foundation models have documented, verifiable provenance. "
                    "Model origin (vendor, version, commit hash) is recorded and "
                    "linked to model containers/binaries."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S1", "S2", "S3", "S4"],
                t1_criteria=[
                    "Model provenance is documented in deployment manifests",
                    "Model source (registry, hash) is versioned and traceable",
                ],
                t2_criteria=[
                    "Model registry URL and digest/hash present in deployment",
                    "Model metadata file contains provenance information",
                ],
                nist_mapping=["SA-3", "SA-8"],
                owasp_mapping=["LLM03"],
                cwe_mapping=["CWE-829"],
                tags=["provenance", "model", "traceability"],
            ),
            ControlDefinition(
                control_id="D1.2",
                domain_id="D1",
                name="Model Code Hash Verification",
                description=(
                    "Model integrity is verified via cryptographic hash. "
                    "Runtime system validates model binary against expected hash "
                    "before use."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Hash algorithm (SHA-256, etc.) is specified",
                    "Expected hash value is documented and immutable",
                ],
                t2_criteria=[
                    "Hash validation code present at model load time",
                    "Failure path implemented (reject if hash mismatch)",
                ],
                nist_mapping=["SI-7"],
                owasp_mapping=["LLM03"],
                cwe_mapping=["CWE-353"],
                tags=["integrity", "hash", "verification"],
            ),
            ControlDefinition(
                control_id="D1.3",
                domain_id="D1",
                name="Model Quantization/Distillation Controls",
                description=(
                    "If models are quantized or distilled, transformations are "
                    "controlled, traceable, and audited. Provenance chain is maintained "
                    "from original to transformed model."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Quantization/distillation process is documented",
                    "Transformation parameters (bitwidth, student model) are recorded",
                ],
                t2_criteria=[
                    "Quantization/distillation code is signed or audited",
                    "Output model hash links back to transformation parameters",
                ],
                nist_mapping=["SA-3"],
                owasp_mapping=["LLM03"],
                cwe_mapping=["CWE-829"],
                tags=["quantization", "distillation", "model-transformation"],
            ),
            ControlDefinition(
                control_id="D1.4",
                domain_id="D1",
                name="Model Deployment Signing",
                description=(
                    "Model containers or binaries are cryptographically signed. "
                    "Deployment system verifies signatures before pulling/running models."
                ),
                severity=Severity.CRITICAL,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Signing strategy (container image sig, binary sig) is defined",
                    "Key management for model signing is documented",
                ],
                t2_criteria=[
                    "Model signature verification enforced in deployment pipeline",
                    "Signature algorithm and key identity logged",
                ],
                nist_mapping=["SI-7", "SA-4"],
                owasp_mapping=["LLM03"],
                cwe_mapping=["CWE-347"],
                tags=["signing", "deployment", "integrity"],
            ),
            ControlDefinition(
                control_id="D1.5",
                domain_id="D1",
                name="Runtime Model Patching Control",
                description=(
                    "Models cannot be modified, patched, or replaced at runtime "
                    "without audit trail. Model immutability or change control is enforced."
                ),
                severity=Severity.HIGH,
                applicable_stages=["S2", "S3", "S4"],
                t1_criteria=[
                    "Model patching policy is defined (allowed/disallowed)",
                    "Change control process for model updates is documented",
                ],
                t2_criteria=[
                    "Runtime model loading is read-only (no write access)",
                    "Model updates require restart or signed reload directive",
                    "Audit logging of all model replacement events",
                ],
                nist_mapping=["SI-2", "SI-7"],
                owasp_mapping=["LLM03"],
                cwe_mapping=["CWE-94"],
                tags=["runtime", "patching", "control", "immutability"],
            ),
        ]

    def required_scanners(self) -> list[str]:
        """Scanners required for D1 evaluation."""
        return ["supply_chain", "codebase"]

    def required_analyzers(self) -> list[str]:
        """Analyzers that enhance D1 scoring."""
        return ["semgrep"]

    async def score_controls(
        self,
        scan_results: dict[str, ScanResult],
        analyzer_results: dict[str, ScanResult],
    ) -> list[ControlScore]:
        """Score D1 controls using model registry and code analysis.

        Strategy:
          1. Use model_registry scanner for provenance, hash, signing findings
          2. Use codebase scanner for implementation patterns (hash validation,
             quantization tracking, immutability enforcement)
          3. Use semgrep analyzer for model integrity vulnerabilities
          4. Map findings to specific controls
          5. Set T2 floor based on presence of critical patterns + evidence density
        """
        controls = self.define_controls()
        scores: list[ControlScore] = []

        # Extract findings by category for quick lookup
        registry_findings = self._extract_findings_by_category(
            scan_results.get("supply_chain")
        )
        codebase_findings = self._extract_findings_by_category(
            scan_results.get("codebase")
        )
        semgrep_findings = self._extract_findings_by_category(
            analyzer_results.get("semgrep")
        )

        # D1.1: Model Source Provenance
        score_d11 = self._score_d11(
            controls[0],
            registry_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d11)

        # D1.2: Model Code Hash Verification
        score_d12 = self._score_d12(
            controls[1],
            registry_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d12)

        # D1.3: Model Quantization/Distillation Controls
        score_d13 = self._score_d13(
            controls[2],
            registry_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d13)

        # D1.4: Model Deployment Signing
        score_d14 = self._score_d14(
            controls[3],
            registry_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d14)

        # D1.5: Runtime Model Patching Control
        score_d15 = self._score_d15(
            controls[4],
            registry_findings,
            codebase_findings,
            semgrep_findings,
        )
        scores.append(score_d15)

        return scores

    # ------------------------------------------------------------------
    # Per-Control Scoring Logic
    # ------------------------------------------------------------------

    def _score_d11(
        self,
        control_def: ControlDefinition,
        registry_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D1.1: Model Source Provenance"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for model provenance records in model_registry scanner
        if registry_findings.get("model_provenance"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:model_registry",
                description="Model provenance metadata found in registry manifests",
                confidence=0.85,
            ))

        # Check for registry URL/digest patterns in codebase
        if codebase_findings.get("registry_url"):
            t2_floor = max(t2_floor, 5.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Model registry URLs with version/digest references found in code",
                confidence=0.75,
            ))

        # Check for model hash references in registry manifests
        if registry_findings.get("registry_hash"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:model_registry",
                description="Model hash/digest present in registry configuration",
                confidence=0.9,
            ))

        # Check for model metadata files (model cards, provenance docs)
        if codebase_findings.get("model_metadata"):
            t2_floor = max(t2_floor, 5.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Model metadata or model card files detected",
                confidence=0.7,
            ))

        # Negative evidence: missing provenance in semgrep
        if semgrep_findings.get("missing_provenance"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep identified model loading without provenance checks (negative evidence)",
                confidence=0.75,
            ))
            # Cap T2 if provenance gaps detected
            t2_floor = min(t2_floor, 3.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No model provenance documentation found"] if t2_floor == 0 else [],
        )

    def _score_d12(
        self,
        control_def: ControlDefinition,
        registry_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D1.2: Model Code Hash Verification"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for hash validation logic in codebase
        if codebase_findings.get("hash_validation"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Hash validation code found at model load time",
                confidence=0.8,
            ))

        # Check for hash algorithm patterns (SHA-256, SHA-512, etc.)
        if codebase_findings.get("hash_algorithm"):
            t2_floor = max(t2_floor, 5.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Cryptographic hash algorithm (SHA-256/SHA-512) used for model verification",
                confidence=0.75,
            ))

        # Check for hash mismatch rejection (failure path)
        if codebase_findings.get("hash_mismatch_reject"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Model rejection on hash mismatch implemented (fail-closed)",
                confidence=0.85,
            ))

        # Check for expected hash values in registry
        if registry_findings.get("registry_hash"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:model_registry",
                description="Expected model hash values stored in registry configuration",
                confidence=0.8,
            ))

        # Negative evidence: model loaded without hash check
        if semgrep_findings.get("unverified_model_load"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep detected model loading paths without hash verification (negative evidence)",
                confidence=0.8,
            ))
            # Cap T2 if unverified loads detected
            t2_floor = min(t2_floor, 2.5)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No model hash verification found"] if t2_floor == 0 else [],
        )

    def _score_d13(
        self,
        control_def: ControlDefinition,
        registry_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D1.3: Model Quantization/Distillation Controls"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for quantization tracking in registry
        if registry_findings.get("quantization_tracking"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:model_registry",
                description="Quantization parameters tracked in model registry metadata",
                confidence=0.8,
            ))

        # Check for transformation audit trail in codebase
        if codebase_findings.get("transformation_audit"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Model transformation audit trail found (quantization/distillation logging)",
                confidence=0.75,
            ))

        # Check for distillation provenance chain
        if codebase_findings.get("distillation_provenance"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Distillation provenance chain links transformed model to source",
                confidence=0.8,
            ))

        # Check for transformation parameters recorded (bitwidth, method)
        if codebase_findings.get("quantization_params"):
            t2_floor = max(t2_floor, 5.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Quantization parameters (bitwidth, method) recorded in code or config",
                confidence=0.7,
            ))

        # Negative evidence: untracked transformations
        if semgrep_findings.get("untracked_transformation"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep detected model transformation without audit/tracking (negative evidence)",
                confidence=0.7,
            ))
            # Cap T2 if untracked transformations found
            t2_floor = min(t2_floor, 2.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No quantization/distillation tracking found"] if t2_floor == 0 else [],
        )

    def _score_d14(
        self,
        control_def: ControlDefinition,
        registry_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D1.4: Model Deployment Signing"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for deployment signing configuration in registry
        if registry_findings.get("deployment_signing"):
            t2_floor = 6.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:model_registry",
                description="Model deployment signing configuration found in registry",
                confidence=0.8,
            ))

        # Check for cosign/notary verification in codebase
        if codebase_findings.get("cosign_verification"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Cosign/Notary container image signature verification found",
                confidence=0.85,
            ))

        # Check for generic signature verification code
        if codebase_findings.get("signature_verification"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Cryptographic signature verification logic in deployment pipeline",
                confidence=0.8,
            ))

        # Check for signing key management
        if codebase_findings.get("signing_key_management"):
            t2_floor = max(t2_floor, 7.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Signing key management (rotation, storage) implemented",
                confidence=0.75,
            ))

        # Negative evidence: unsigned deployment detected
        if semgrep_findings.get("unsigned_deployment"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep detected deployment paths without signature verification (negative evidence)",
                confidence=0.8,
            ))
            # Cap T2 if unsigned deployments found
            t2_floor = min(t2_floor, 2.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=3.0,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No model deployment signing found"] if t2_floor == 0 else [],
        )

    def _score_d15(
        self,
        control_def: ControlDefinition,
        registry_findings: dict[str, list[ScanFinding]],
        codebase_findings: dict[str, list[ScanFinding]],
        semgrep_findings: dict[str, list[ScanFinding]],
    ) -> ControlScore:
        """D1.5: Runtime Model Patching Control"""
        evidence: list[ControlEvidence] = []
        t2_floor = 0.0

        # Check for model immutability enforcement
        if codebase_findings.get("model_immutable"):
            t2_floor = 7.0
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Model immutability enforcement found (read-only loading)",
                confidence=0.85,
            ))

        # Check for read-only filesystem for model storage
        if codebase_findings.get("readonly_filesystem"):
            t2_floor = max(t2_floor, 7.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Read-only filesystem or volume mount for model storage configured",
                confidence=0.8,
            ))

        # Check for runtime patch control / audit logging
        if codebase_findings.get("runtime_patch_control"):
            t2_floor = max(t2_floor, 6.5)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:codebase",
                description="Runtime model patch control with audit logging implemented",
                confidence=0.75,
            ))

        # Check for model replacement audit in registry
        if registry_findings.get("model_replacement_audit"):
            t2_floor = max(t2_floor, 6.0)
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.SCANNER,
                source_tool="scanner:model_registry",
                description="Model replacement events audited in registry",
                confidence=0.75,
            ))

        # Negative evidence: writable model paths or uncontrolled patching
        if semgrep_findings.get("writable_model_path"):
            evidence.append(ControlEvidence(
                tier=EvidenceTier.T2_IMPLEMENTATION,
                source=EvidenceSource.ANALYZER,
                source_tool="analyzer:semgrep",
                description="Semgrep detected writable model paths or uncontrolled runtime patching (negative evidence)",
                confidence=0.8,
            ))
            # Cap T2 if writable model paths found
            t2_floor = min(t2_floor, 2.0)

        return self._make_control_score(
            control_def.control_id,
            control_def.name,
            t1=2.5,  # Default design baseline
            t2=t2_floor,
            status=ControlStatus.PARTIALLY_IMPLEMENTED if t2_floor > 0 else ControlStatus.NOT_REVIEWED,
            evidence=evidence,
            gaps=["No runtime model patching controls found"] if t2_floor == 0 else [],
        )

    # ------------------------------------------------------------------
    # Utility Methods
    # ------------------------------------------------------------------

    def _extract_findings_by_category(
        self,
        scan_result: Optional[ScanResult],
    ) -> dict[str, list[ScanFinding]]:
        """Extract findings from a ScanResult and group by category."""
        if not scan_result:
            return {}
        by_category: dict[str, list[ScanFinding]] = {}
        for finding in scan_result.findings:
            if finding.category not in by_category:
                by_category[finding.category] = []
            by_category[finding.category].append(finding)
        return by_category
