"""
IIoT/OT Scanner

Detects operational technology interfaces, safety interlocks,
and physical device control patterns.
"""

from __future__ import annotations

import re

from asopb.models import ScanResult, Severity
from asopb.scanner.base import ScannerBase


class ITOTScanner(ScannerBase):
    """Detects Industrial IoT (IIoT) and Operational Technology (OT) patterns.

    Identifies:
    - Instrument control interfaces
    - Safety interlocks and E-Stop mechanisms
    - HITL (Human-in-the-Loop) gates
    - Physical device APIs
    - PLC/SCADA system interaction
    - Equipment control sequences
    - Emergency stop patterns
    - Interlocking logic
    - Device communication protocols
    - State machine patterns for safety
    """

    name = "itot"
    description = "Industrial IoT and OT interface detection"

    # Instrument control patterns
    INSTRUMENT_PATTERNS = [
        r"instrument",
        r"device.*control",
        r"hardware.*interface",
        r"board.*control",
        r"actuator",
        r"motor.*control",
        r"sensor.*read",
        r"gpio",
        r"GPIO",
        r"pwm",
        r"PWM",
        r"dac",
        r"adc",
        r"ADC",
        r"calibration",
    ]

    # Physical device APIs (Opentrons, etc.)
    PHYSICAL_DEVICE_PATTERNS = [
        r"opentrons",
        r"Opentrons",
        r"robot.*control",
        r"pipette.*control",
        r"deck.*layout",
        r"protocol.*run",
        r"hardware.*module",
        r"instrument.*library",
        r"labware",
        r"pipetting",
    ]

    # Safety interlock patterns
    SAFETY_INTERLOCK_PATTERNS = [
        r"safety.*check",
        r"safety.*interlock",
        r"interlock",
        r"safety.*gate",
        r"guard.*check",
        r"safe.*state",
        r"hazard.*check",
        r"permissive.*check",
        r"enable.*check",
        r"inhibit.*mechanism",
    ]

    # E-Stop patterns
    ESTOP_PATTERNS = [
        r"e.*stop",
        r"e-stop",
        r"emergency.*stop",
        r"estop",
        r"ESTOP",
        r"emergency.*shutdown",
        r"manual.*stop",
        r"panic.*button",
        r"halt.*all",
        r"stop.*immediately",
    ]

    # Human-in-the-loop patterns
    HITL_PATTERNS = [
        r"human.*loop",
        r"human.*approval",
        r"manual.*approval",
        r"operator.*confirm",
        r"require.*confirmation",
        r"user.*approval",
        r"interactive.*gate",
        r"pause.*resume",
        r"require_approval",
        r"wait_for_operator",
    ]

    # PLC/SCADA patterns
    PLC_SCADA_PATTERNS = [
        r"plc",
        r"PLC",
        r"scada",
        r"SCADA",
        r"modbus",
        r"Modbus",
        r"profibus",
        r"profinet",
        r"opc.*ua",
        r"can.*bus",
    ]

    # State machine patterns (safety)
    STATE_MACHINE_PATTERNS = [
        r"state.*machine",
        r"finite.*state",
        r"fsm",
        r"state\..*\(\"",
        r"@state",
        r"current.*state",
        r"state.*transition",
        r"valid.*transition",
        r"allowed.*state",
    ]

    # Equipment control sequences
    SEQUENCE_PATTERNS = [
        r"sequence",
        r"protocol",
        r"step.*by.*step",
        r"sequential.*step",
        r"procedure",
        r"workflow",
        r"run.*sequence",
        r"execute.*sequence",
        r"step_\d+",
    ]

    # Device communication patterns
    DEVICE_COMM_PATTERNS = [
        r"serial.*port",
        r"usb.*communication",
        r"ethernet.*device",
        r"grpc.*service",
        r"device.*api",
        r"rest.*api.*device",
        r"mqtt.*device",
        r"can.*interface",
    ]

    # Critical operation patterns
    CRITICAL_OPS_PATTERNS = [
        r"critical.*operation",
        r"high.*risk",
        r"dangerous.*operation",
        r"irreversible.*action",
        r"point.*of.*no.*return",
        r"fail.*safe",
        r"fail.*soft",
        r"degraded.*mode",
    ]

    async def scan(self) -> ScanResult:
        """Execute IIoT/OT scanner."""
        result = ScanResult(
            tool_name=self.name,
            tool_version="1.0.0",
        )

        findings = []
        stats = {
            "instrument_control": 0,
            "physical_devices": 0,
            "safety_interlocks": 0,
            "estop_mechanisms": 0,
            "hitl_gates": 0,
            "plc_scada": 0,
            "state_machines": 0,
            "sequences": 0,
            "device_communication": 0,
            "critical_operations": 0,
        }

        try:
            # Instrument control detection
            instrument_matches = self.grep(
                "|".join(self.INSTRUMENT_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["instrument_control"] = len(instrument_matches)
            for match in instrument_matches[:3]:
                findings.append(
                    self._make_finding(
                        "instrument_control",
                        f"Instrument control pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Physical device APIs
            device_matches = self.grep(
                "|".join(self.PHYSICAL_DEVICE_PATTERNS),
                glob="**/*",
                ignore_case=True,
                max_results=1,
            )
            if device_matches:
                stats["physical_devices"] = len(device_matches)
                findings.append(
                    self._make_finding(
                        "physical_device_api",
                        f"Physical device API detected: {device_matches[0].match_text}",
                        file_path=device_matches[0].file_path,
                        line_number=device_matches[0].line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Safety interlocks
            interlock_matches = self.grep(
                "|".join(self.SAFETY_INTERLOCK_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["safety_interlocks"] = len(interlock_matches)
            for match in interlock_matches[:3]:
                findings.append(
                    self._make_finding(
                        "safety_interlock",
                        f"Safety interlock pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # E-Stop detection
            estop_matches = self.grep(
                "|".join(self.ESTOP_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["estop_mechanisms"] = len(estop_matches)
            for match in estop_matches[:3]:
                findings.append(
                    self._make_finding(
                        "estop_mechanism",
                        f"E-Stop/emergency shutdown pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # HITL gates
            hitl_matches = self.grep(
                "|".join(self.HITL_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["hitl_gates"] = len(hitl_matches)
            for match in hitl_matches[:3]:
                findings.append(
                    self._make_finding(
                        "hitl_gate",
                        f"Human-in-the-loop gate: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # PLC/SCADA detection
            plc_matches = self.grep(
                "|".join(self.PLC_SCADA_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["plc_scada"] = len(plc_matches)
            for match in plc_matches[:3]:
                findings.append(
                    self._make_finding(
                        "plc_scada",
                        f"PLC/SCADA pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # State machines
            state_matches = self.grep(
                "|".join(self.STATE_MACHINE_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["state_machines"] = len(state_matches)
            for match in state_matches[:3]:
                findings.append(
                    self._make_finding(
                        "state_machine",
                        f"State machine pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Equipment sequences
            seq_matches = self.grep(
                "|".join(self.SEQUENCE_PATTERNS),
                glob="**/*.py",
                ignore_case=True,
            )
            stats["sequences"] = len(seq_matches)
            for match in seq_matches[:3]:
                findings.append(
                    self._make_finding(
                        "equipment_sequence",
                        f"Equipment sequence pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Device communication
            comm_matches = self.grep(
                "|".join(self.DEVICE_COMM_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["device_communication"] = len(comm_matches)
            for match in comm_matches[:3]:
                findings.append(
                    self._make_finding(
                        "device_communication",
                        f"Device communication pattern: {match.match_text}",
                        file_path=match.file_path,
                        line_number=match.line_number,
                        severity=Severity.INFORMATIONAL,
                    )
                )

            # Critical operations
            crit_matches = self.grep(
                "|".join(self.CRITICAL_OPS_PATTERNS),
                glob="**/*",
                ignore_case=True,
            )
            stats["critical_operations"] = len(crit_matches)
            for match in crit_matches[:3]:
                findings.append(
                    self._make_finding(
                        "critical_operation",
                        f"Critical operation pattern: {match.match_text}",
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
