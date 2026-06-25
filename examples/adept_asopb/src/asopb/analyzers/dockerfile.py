"""
Dockerfile Analyzer

Custom analyzer for scanning Dockerfiles and docker-compose files for security
issues including privileged flags, running as root, exposed ports, insecure COPY/ADD,
and secrets in build arguments.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

import yaml

from asopb.analyzers.base import AnalyzerBase
from asopb.models import ScanFinding, ScanResult, Severity


class DockerfileAnalyzer(AnalyzerBase):
    """Analyzer for Dockerfile and docker-compose security issues.

    Custom analyzer that scans Dockerfiles for security anti-patterns:
    - Running as root
    - Privileged flags
    - Exposed ports
    - Use of ADD instead of COPY
    - Secrets in build arguments
    - Also checks docker-compose for privileged mode, host network, docker.sock mounts
    """

    name = "dockerfile"
    description = "Dockerfile security analysis (privileged, root, secrets, etc.)"
    tool_command = ""  # No external tool required

    def is_available(self) -> bool:
        """Always available - no external tool dependency."""
        return True

    async def analyze(self) -> ScanResult:
        """Scan Dockerfiles and docker-compose files in the repository.

        Returns:
            ScanResult with parsed findings
        """
        start_time = time.time()

        findings = []
        raw_output_lines = []

        # Scan Dockerfiles
        dockerfile_findings, dockerfile_output = self._scan_dockerfiles()
        findings.extend(dockerfile_findings)
        raw_output_lines.extend(dockerfile_output)

        # Scan docker-compose files
        compose_findings, compose_output = self._scan_docker_compose()
        findings.extend(compose_findings)
        raw_output_lines.extend(compose_output)

        duration = time.time() - start_time
        raw_output = "\n".join(raw_output_lines) if raw_output_lines else None

        return self._make_result(
            success=True,
            findings=findings,
            raw_output=raw_output,
            duration=duration,
        )

    def _scan_dockerfiles(self) -> tuple[list[ScanFinding], list[str]]:
        """Scan all Dockerfiles in the repository.

        Returns:
            Tuple of (findings, raw output lines)
        """
        findings = []
        output = []

        # Find all Dockerfiles
        dockerfile_patterns = ["Dockerfile", "Dockerfile.*", "*/Dockerfile"]
        dockerfile_paths = set()

        for pattern in dockerfile_patterns:
            dockerfile_paths.update(self.repo_path.glob(pattern))

        # Also check for files named Dockerfile* in any subdirectory
        dockerfile_paths.update(self.repo_path.rglob("Dockerfile*"))

        for dockerfile_path in dockerfile_paths:
            if not dockerfile_path.is_file():
                continue

            try:
                content = dockerfile_path.read_text()
                relative_path = dockerfile_path.relative_to(self.repo_path)
                output.append(f"Scanning {relative_path}")

                # Check for security issues
                dockerfile_findings = self._analyze_dockerfile(content, relative_path)
                findings.extend(dockerfile_findings)

            except (IOError, OSError) as e:
                output.append(f"Error reading {dockerfile_path}: {e}")

        return findings, output

    def _scan_docker_compose(self) -> tuple[list[ScanFinding], list[str]]:
        """Scan docker-compose files in the repository.

        Returns:
            Tuple of (findings, raw output lines)
        """
        findings = []
        output = []

        # Find docker-compose files
        compose_patterns = [
            "docker-compose.yml",
            "docker-compose.yaml",
            "*/docker-compose.yml",
            "*/docker-compose.yaml",
        ]
        compose_paths = set()

        for pattern in compose_patterns:
            compose_paths.update(self.repo_path.glob(pattern))

        compose_paths.update(self.repo_path.rglob("docker-compose.y*ml"))

        for compose_path in compose_paths:
            if not compose_path.is_file():
                continue

            try:
                content = compose_path.read_text()
                relative_path = compose_path.relative_to(self.repo_path)
                output.append(f"Scanning {relative_path}")

                compose_findings = self._analyze_docker_compose(content, relative_path)
                findings.extend(compose_findings)

            except (IOError, OSError, yaml.YAMLError) as e:
                output.append(f"Error reading {compose_path}: {e}")

        return findings, output

    def _analyze_dockerfile(self, content: str, filepath: Path) -> list[ScanFinding]:
        """Analyze a Dockerfile for security issues.

        Args:
            content: Dockerfile content
            filepath: Path to the Dockerfile

        Returns:
            List of findings
        """
        findings = []
        lines = content.split("\n")
        finding_count = 0

        for line_num, line in enumerate(lines, 1):
            # Skip comments and empty lines
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Check for USER root or missing USER directive
            if re.search(r"^\s*USER\s+root\s*$", line, re.IGNORECASE):
                findings.append(
                    ScanFinding(
                        finding_id=f"dockerfile-{finding_count}",
                        category="root_user",
                        severity=Severity.HIGH,
                        file_path=str(filepath),
                        line_number=line_num,
                        message="Dockerfile runs as root (USER root)",
                        snippet=line.strip(),
                        confidence=1.0,
                        metadata={"issue_type": "root_user"},
                    )
                )
                finding_count += 1

            # Check for privileged flag in RUN or ENTRYPOINT
            if re.search(r"--privileged", line, re.IGNORECASE):
                findings.append(
                    ScanFinding(
                        finding_id=f"dockerfile-{finding_count}",
                        category="privileged_flag",
                        severity=Severity.HIGH,
                        file_path=str(filepath),
                        line_number=line_num,
                        message="Privileged flag used in container",
                        snippet=line.strip(),
                        confidence=1.0,
                        metadata={"issue_type": "privileged_flag"},
                    )
                )
                finding_count += 1

            # Check for ADD instruction (should use COPY instead)
            if re.search(r"^\s*ADD\s+", line, re.IGNORECASE):
                findings.append(
                    ScanFinding(
                        finding_id=f"dockerfile-{finding_count}",
                        category="add_instead_of_copy",
                        severity=Severity.MEDIUM,
                        file_path=str(filepath),
                        line_number=line_num,
                        message="ADD instruction used; COPY is more secure",
                        snippet=line.strip(),
                        confidence=0.9,
                        metadata={"issue_type": "add_instead_of_copy"},
                    )
                )
                finding_count += 1

            # Check for secrets in ARG/ENV
            if re.search(r"(ARG|ENV)\s+\w*(PASS|TOKEN|KEY|SECRET)\w*=", line, re.IGNORECASE):
                findings.append(
                    ScanFinding(
                        finding_id=f"dockerfile-{finding_count}",
                        category="secret_in_build_arg",
                        severity=Severity.CRITICAL,
                        file_path=str(filepath),
                        line_number=line_num,
                        message="Potential secret in build argument",
                        snippet=line.strip(),
                        confidence=0.85,
                        metadata={"issue_type": "secret_in_build_arg"},
                    )
                )
                finding_count += 1

            # Check for apt-get without --no-install-recommends
            if re.search(r"apt-get\s+install", line, re.IGNORECASE):
                if "--no-install-recommends" not in line:
                    findings.append(
                        ScanFinding(
                            finding_id=f"dockerfile-{finding_count}",
                            category="apt_without_no_install_recommends",
                            severity=Severity.LOW,
                            file_path=str(filepath),
                            line_number=line_num,
                            message="apt-get install without --no-install-recommends",
                            snippet=line.strip(),
                            confidence=0.95,
                            metadata={"issue_type": "apt_without_no_install_recommends"},
                        )
                    )
                    finding_count += 1

            # Check for exposed ports (informational)
            if re.search(r"^\s*EXPOSE\s+", line, re.IGNORECASE):
                port = re.search(r"EXPOSE\s+(\d+)", line, re.IGNORECASE)
                if port:
                    findings.append(
                        ScanFinding(
                            finding_id=f"dockerfile-{finding_count}",
                            category="exposed_port",
                            severity=Severity.INFORMATIONAL,
                            file_path=str(filepath),
                            line_number=line_num,
                            message=f"Port {port.group(1)} exposed",
                            snippet=line.strip(),
                            confidence=1.0,
                            metadata={"issue_type": "exposed_port", "port": port.group(1)},
                        )
                    )
                    finding_count += 1

        return findings

    def _analyze_docker_compose(self, content: str, filepath: Path) -> list[ScanFinding]:
        """Analyze a docker-compose file for security issues.

        Args:
            content: docker-compose YAML content
            filepath: Path to the file

        Returns:
            List of findings
        """
        findings = []
        finding_count = 0

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            return findings

        if not data or not isinstance(data, dict):
            return findings

        services = data.get("services", {})
        for service_name, service_config in services.items():
            if not isinstance(service_config, dict):
                continue

            # Check for privileged mode
            if service_config.get("privileged") is True:
                findings.append(
                    ScanFinding(
                        finding_id=f"compose-{finding_count}",
                        category="docker_compose_privileged",
                        severity=Severity.HIGH,
                        file_path=str(filepath),
                        message=f"Service '{service_name}' runs with privileged: true",
                        confidence=1.0,
                        metadata={
                            "issue_type": "docker_compose_privileged",
                            "service": service_name,
                        },
                    )
                )
                finding_count += 1

            # Check for host network mode
            if service_config.get("network_mode") == "host":
                findings.append(
                    ScanFinding(
                        finding_id=f"compose-{finding_count}",
                        category="docker_compose_host_network",
                        severity=Severity.HIGH,
                        file_path=str(filepath),
                        message=f"Service '{service_name}' uses host network mode",
                        confidence=1.0,
                        metadata={
                            "issue_type": "docker_compose_host_network",
                            "service": service_name,
                        },
                    )
                )
                finding_count += 1

            # Check for docker.sock mounts
            volumes = service_config.get("volumes", [])
            for volume in volumes:
                if isinstance(volume, str):
                    if "/var/run/docker.sock" in volume:
                        findings.append(
                            ScanFinding(
                                finding_id=f"compose-{finding_count}",
                                category="docker_sock_mount",
                                severity=Severity.CRITICAL,
                                file_path=str(filepath),
                                message=f"Service '{service_name}' mounts docker.sock",
                                snippet=volume,
                                confidence=1.0,
                                metadata={
                                    "issue_type": "docker_sock_mount",
                                    "service": service_name,
                                    "volume": volume,
                                },
                            )
                        )
                        finding_count += 1

        return findings
