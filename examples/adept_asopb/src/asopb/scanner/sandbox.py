"""
Sandbox Scanner

Detects isolation and sandboxing mechanisms including Docker, nsjail,
llm-sandbox, and other containment strategies.
"""

from __future__ import annotations

import re

from asopb.models import ScanResult, Severity
from asopb.scanner.base import ScannerBase


class SandboxScanner(ScannerBase):
    """Detects sandboxing and isolation mechanisms.

    Identifies:
    - Docker containerization (Dockerfile, docker-compose)
    - Sandbox-specific Dockerfiles
    - nsjail configuration
    - llm-sandbox usage
    - Privileged container flags
    - Read-only filesystems
    - Capability dropping
    - Resource limits
    - Network isolation
    - Security profiles (AppArmor, SELinux)
    """

    name = "sandbox"
    description = "Sandboxing and isolation mechanism detection"

    # Docker patterns
    DOCKER_PATTERNS = [
        r"FROM\s+\w+:\w+",
        r"RUN\s+",
        r"WORKDIR\s+",
        r"COPY\s+",
        r"ADD\s+",
        r"EXPOSE\s+",
        r"ENV\s+",
        r"CMD\s+\[",
        r"ENTRYPOINT\s+\[",
    ]

    # Sandbox-specific patterns
    SANDBOX_DOCKERFILE_PATTERNS = [
        r"Dockerfile\.sandbox",
        r"sandbox.*Dockerfile",
        r"restricted.*Dockerfile",
    ]

    # nsjail patterns
    NSJAIL_PATTERNS = [
        r"nsjail",
        r"nsjail\.config",
        r"nsjail\s+",
        r"-C.*\.cfg",
        r"--config",
    ]

    # llm-sandbox patterns
    LLM_SANDBOX_PATTERNS = [
        r"llm.sandbox",
        r"llm-sandbox",
        r"from.*sandbox",
        r"import.*sandbox",
        r"Sandbox\(",
        r"SandboxedExecution",
    ]

    # Security-relevant Docker flags and configurations
    PRIVILEGED_FLAGS = [
        r"--privileged",
        r"privileged:\s*true",
        r"\"privileged\"\s*:\s*true",
        r"privileged: true",
    ]

    # Capability dropping (security best practice)
    CAPABILITIES_PATTERNS = [
        r"--cap-drop",
        r"cap_drop",
        r"cap_add",
        r"--cap-add",
        r"capabilities:",
        r"securityContext",
        r"capabilities\[",
    ]

    # Read-only filesystem patterns
    READONLY_PATTERNS = [
        r"--read-only",
        r"read-only",
        r"readonly:\s*true",
        r"readOnly:\s*true",
        r"fsGroup",
        r"runAsNonRoot",
        r"runAsUser",
    ]

    # Resource limit patterns
    RESOURCE_LIMIT_PATTERNS = [
        r"--memory",
        r"--cpus",
        r"--ulimit",
        r"memory.*limit",
        r"cpu.*limit",
        r"resources:",
        r"limits:",
        r"requests:",
    ]

    # Network isolation patterns
    NETWORK_ISOLATION_PATTERNS = [
        r"--network.*none",
        r"--network=none",
        r"networkPolicy",
        r"network.*policy",
        r"egress.*deny",
        r"ingress.*deny",
        r"network.*restricted",
        r"--net=none",
    ]

    # Security profiles (AppArmor, SELinux)
    SECURITY_PROFILE_PATTERNS = [
        r"apparmor",
        r"selinux",
        r"securityContext",
        r"seccomp",
        r"security_opt",
        r"--security-opt",
    ]

    # User context patterns
    USER_CONTEXT_PATTERNS = [
        r"USER\s+\d+",
        r"RUN.*useradd",
        r"runAsNonRoot:\s*true",
        r"runAsUser:\s*\d+",
        r"groupId:\s*\d+",
    ]

    # Volume/mount isolation patterns
    VOLUME_PATTERNS = [
        r"VOLUME\s+\[",
        r"volumes:",
        r"volumeMounts:",
        r"-v\s+/",
        r"--mount",
        r"--volume",
    ]

    async def scan(self) -> ScanResult:
        """Execute sandbox scanner."""
        result = ScanResult(
            tool_name=self.name,
            tool_version="1.0.0",
        )

        findings = []
        stats = {
            "docker_found": False,
            "sandbox_dockerfile": False,
            "nsjail_found": False,
            "llm_sandbox_found": False,
            "privileged_flags": 0,
            "capabilities_managed": 0,
            "readonly_filesystem": 0,
            "resource_limits": 0,
            "network_isolation": 0,
            "security_profiles": 0,
            "user_context": 0,
            "volume_isolation": 0,
        }

        try:
            # Check for Docker files
            docker_files = self.find_files("Dockerfile*")
            if docker_files:
                stats["docker_found"] = True
                for df in docker_files:
                    rel_path = str(df.relative_to(self.repo_path))
                    findings.append(
                        self._make_finding(
                            "docker_found",
                            f"Docker container configuration found: {rel_path}",
                            file_path=rel_path,
                            severity=Severity.INFORMATIONAL,
                        )
                    )

            # Check for sandbox-specific Dockerfile
            sandbox_dockerfiles = [f for f in docker_files if "sandbox" in f.name.lower()]
            if sandbox_dockerfiles:
                stats["sandbox_dockerfile"] = True
                for df in sandbox_dockerfiles:
                    rel_path = str(df.relative_to(self.repo_path))
                    findings.append(
                        self._make_finding(
                            "sandbox_dockerfile",
                            f"Sandbox-specific Dockerfile found: {rel_path}",
                            file_path=rel_path,
                            severity=Severity.INFORMATIONAL,
                        )
                    )

            # Check for docker-compose
            if self.file_exists("docker-compose.yml") or self.file_exists("docker-compose.yaml"):
                findings.append(
                    self._make_finding(
                        "docker_compose_found",
                        "Docker Compose configuration found",
                        file_path="docker-compose.yml",
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # nsjail detection
            nsjail_matches = self.grep(
                "|".join(self.NSJAIL_PATTERNS),
                glob="**/*",
                ignore_case=True,
                max_results=1,
            )
            if nsjail_matches:
                stats["nsjail_found"] = True
                findings.append(
                    self._make_finding(
                        "nsjail_found",
                        f"nsjail sandbox detected: {nsjail_matches[0].match_text}",
                        file_path=nsjail_matches[0].file_path,
                        line_number=nsjail_matches[0].line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # llm-sandbox detection
            llm_sandbox_matches = self.grep(
                "|".join(self.LLM_SANDBOX_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
                max_results=1,
            )
            if llm_sandbox_matches:
                stats["llm_sandbox_found"] = True
                findings.append(
                    self._make_finding(
                        "llm_sandbox_found",
                        f"llm-sandbox detected: {llm_sandbox_matches[0].match_text}",
                        file_path=llm_sandbox_matches[0].file_path,
                        line_number=llm_sandbox_matches[0].line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Privileged flag detection (anti-pattern)
            priv_matches = self.grep(
                "|".join(self.PRIVILEGED_FLAGS),
                glob="**/*",
                ignore_case=False,
            )
            stats["privileged_flags"] = len(priv_matches)
            for match in priv_matches:
                findings.append(
                    self._make_finding(
                        "privileged_flag_detected",
                        f"Privileged container flag found: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.HIGH,
                        confidence=0.95,
                    )
                )

            # Capabilities management
            cap_matches = self.grep(
                "|".join(self.CAPABILITIES_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["capabilities_managed"] = len(cap_matches)
            for match in cap_matches[:3]:
                findings.append(
                    self._make_finding(
                        "capabilities_management",
                        f"Capability management pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Read-only filesystem
            readonly_matches = self.grep(
                "|".join(self.READONLY_PATTERNS),
                glob="**/*",
                ignore_case=False,
            )
            stats["readonly_filesystem"] = len(readonly_matches)
            for match in readonly_matches[:3]:
                findings.append(
                    self._make_finding(
                        "readonly_filesystem",
                        f"Read-only filesystem pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Resource limits
            resource_matches = self.grep(
                "|".join(self.RESOURCE_LIMIT_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["resource_limits"] = len(resource_matches)
            for match in resource_matches[:3]:
                findings.append(
                    self._make_finding(
                        "resource_limits",
                        f"Resource limit pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Network isolation
            net_matches = self.grep(
                "|".join(self.NETWORK_ISOLATION_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["network_isolation"] = len(net_matches)
            for match in net_matches[:3]:
                findings.append(
                    self._make_finding(
                        "network_isolation",
                        f"Network isolation pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Security profiles
            sec_matches = self.grep(
                "|".join(self.SECURITY_PROFILE_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["security_profiles"] = len(sec_matches)
            for match in sec_matches[:3]:
                findings.append(
                    self._make_finding(
                        "security_profile",
                        f"Security profile pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # User context
            user_matches = self.grep(
                "|".join(self.USER_CONTEXT_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["user_context"] = len(user_matches)
            for match in user_matches[:3]:
                findings.append(
                    self._make_finding(
                        "user_context",
                        f"User context pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Volume isolation
            vol_matches = self.grep(
                "|".join(self.VOLUME_PATTERNS),
                glob="**/*",
                ignore_case=False,
            )
            stats["volume_isolation"] = len(vol_matches)
            for match in vol_matches[:3]:
                findings.append(
                    self._make_finding(
                        "volume_pattern",
                        f"Volume/mount pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            result.findings = findings
            result.summary_stats = stats
            result.success = True

        except Exception as e:
            result.success = False
            result.error_message = str(e)

        return result
