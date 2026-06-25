#!/usr/bin/env python3
"""
Batch Verification: AWS Bedrock Access for All Workshop Participants

Purpose: Run bedrock instance role verification across all workshop EC2 instances
         using AWS Systems Manager Session Manager (no SSH required)

Usage:
    # Verify all participants in a workshop
    python3 scripts/workshop/verify-bedrock-access-all-participants.py \
        --workshop-id workshop-2026-01

    # Verify specific participants
    python3 scripts/workshop/verify-bedrock-access-all-participants.py \
        --workshop-id workshop-2026-01 \
        --participants scientist1,scientist3

    # Parallel execution (faster for large workshops)
    python3 scripts/workshop/verify-bedrock-access-all-participants.py \
        --workshop-id workshop-2026-01 \
        --parallel 5

    # Generate JSON report
    python3 scripts/workshop/verify-bedrock-access-all-participants.py \
        --workshop-id workshop-2026-01 \
        --output-format json \
        --output-file verification-report.json

Exit codes:
    0 - All participants passed verification
    1 - Some participants failed verification
    2 - Cannot access workshop deployment data
    3 - SSM Session Manager not available
"""

import argparse
import boto3
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict


@dataclass
class VerificationResult:
    """Result of verification for a single participant."""

    participant: str
    instance_id: str
    success: bool
    tests_passed: int
    tests_total: int
    role_arn: Optional[str] = None
    error_message: Optional[str] = None
    execution_time_seconds: float = 0.0
    timestamp: str = ""


class WorkshopVerifier:
    """Orchestrates Bedrock instance role verification across workshop participants."""

    def __init__(self, workshop_id: str, region: str = "us-west-2"):
        self.workshop_id = workshop_id
        self.region = region
        self.ssm_client = boto3.client("ssm", region_name=region)
        self.ec2_client = boto3.client("ec2", region_name=region)
        self.cfn_client = boto3.client("cloudformation", region_name=region)
        self.dynamodb = boto3.resource("dynamodb", region_name=region)

    def get_workshop_participants(
        self, specific_participants: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Get list of workshop participants from DynamoDB or CloudFormation.

        Args:
            specific_participants: Optional list of specific participant usernames

        Returns:
            List of participant dicts with username, instance_id, env
        """
        # Try DynamoDB table first (preferred for workshops)
        try:
            table = self.dynamodb.Table("adept-workshop-deployments")
            response = table.query(
                KeyConditionExpression="workshop_id = :wid",
                ExpressionAttributeValues={":wid": self.workshop_id},
            )

            participants = []
            for item in response["Items"]:
                username = item.get("user")
                if specific_participants and username not in specific_participants:
                    continue

                participants.append(
                    {
                        "username": username,
                        "instance_id": item.get("ec2_instance_id"),
                        "env": item.get("environment", "dev"),
                        "role_arn": item.get("role_arn"),
                    }
                )

            if participants:
                return participants

        except Exception as e:
            print(f"⚠️  DynamoDB table not found or error: {e}")
            print("   Falling back to CloudFormation stack discovery...")

        # Fall back to CloudFormation stack discovery
        return self._discover_participants_from_cfn(specific_participants)

    def _discover_participants_from_cfn(
        self, specific_participants: Optional[List[str]] = None
    ) -> List[Dict]:
        """Discover participants from CloudFormation stacks."""
        participants = []

        # List all CloudFormation stacks matching pattern
        paginator = self.cfn_client.get_paginator("describe_stacks")

        for page in paginator.paginate():
            for stack in page["Stacks"]:
                stack_name = stack["StackName"]

                # Match pattern: ADE-{env}-{user}-Stack
                if not stack_name.startswith("ADE-"):
                    continue
                if stack["StackStatus"] in [
                    "DELETE_COMPLETE",
                    "DELETE_IN_PROGRESS",
                    "ROLLBACK_COMPLETE",
                ]:
                    continue

                parts = stack_name.split("-")
                if len(parts) < 4:
                    continue

                env = parts[1]
                username = parts[2]

                if specific_participants and username not in specific_participants:
                    continue

                # Extract instance ID and role ARN from stack outputs
                outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}

                instance_id = outputs.get("InstanceId")
                role_arn = outputs.get("InstanceRoleArn")

                if instance_id:
                    participants.append(
                        {
                            "username": username,
                            "instance_id": instance_id,
                            "env": env,
                            "role_arn": role_arn,
                            "stack_name": stack_name,
                        }
                    )

        return participants

    def verify_participant(self, participant: Dict) -> VerificationResult:
        """
        Run verification script on a single participant's EC2 instance via SSM.

        Args:
            participant: Participant dict with instance_id and username

        Returns:
            VerificationResult with test outcomes
        """
        instance_id = participant["instance_id"]
        username = participant["username"]

        print(f"🔍 Verifying {username} (instance: {instance_id})...")

        start_time = time.time()

        try:
            # Check if instance is accessible via SSM
            if not self._check_ssm_connectivity(instance_id):
                return VerificationResult(
                    participant=username,
                    instance_id=instance_id,
                    success=False,
                    tests_passed=0,
                    tests_total=7,
                    error_message="Instance not accessible via SSM Session Manager",
                    execution_time_seconds=time.time() - start_time,
                    timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                )

            # Run verification script via SSM
            script_path = (
                "/data/workspace/adept-agentic-framework-extended/"
                "scripts/workshop/verify-bedrock-instance-role.sh"
            )

            response = self.ssm_client.send_command(
                InstanceIds=[instance_id],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": [f"bash {script_path}"]},
                TimeoutSeconds=120,
            )

            command_id = response["Command"]["CommandId"]

            # Wait for command completion
            waiter = self.ssm_client.get_waiter("command_executed")
            waiter.wait(
                CommandId=command_id,
                InstanceId=instance_id,
                WaiterConfig={"Delay": 5, "MaxAttempts": 24},  # 2 minute timeout
            )

            # Get command output
            output_response = self.ssm_client.get_command_invocation(
                CommandId=command_id, InstanceId=instance_id
            )

            stdout = output_response.get("StandardOutputContent", "")
            stderr = output_response.get("StandardErrorContent", "")
            exit_code = output_response.get("ResponseCode", -1)

            # Parse verification results from output
            tests_passed = self._parse_tests_passed(stdout)
            role_arn = self._parse_role_arn(stdout)

            success = exit_code == 0

            return VerificationResult(
                participant=username,
                instance_id=instance_id,
                success=success,
                tests_passed=tests_passed,
                tests_total=7,
                role_arn=role_arn,
                error_message=stderr if not success else None,
                execution_time_seconds=time.time() - start_time,
                timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            )

        except Exception as e:
            return VerificationResult(
                participant=username,
                instance_id=instance_id,
                success=False,
                tests_passed=0,
                tests_total=7,
                error_message=str(e),
                execution_time_seconds=time.time() - start_time,
                timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            )

    def _check_ssm_connectivity(self, instance_id: str) -> bool:
        """Check if EC2 instance is reachable via SSM Session Manager."""
        try:
            response = self.ssm_client.describe_instance_information(
                Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
            )

            if not response["InstanceInformationList"]:
                return False

            instance_info = response["InstanceInformationList"][0]
            ping_status = instance_info.get("PingStatus")

            return ping_status == "Online"

        except Exception:
            return False

    def _parse_tests_passed(self, stdout: str) -> int:
        """Parse number of tests passed from verification script output."""
        # Look for "Passed: X" in output
        for line in stdout.split("\n"):
            if "Passed:" in line:
                try:
                    return int(line.split("Passed:")[1].strip().split()[0])
                except (IndexError, ValueError):
                    pass
        return 0

    def _parse_role_arn(self, stdout: str) -> Optional[str]:
        """Parse IAM role ARN from verification script output."""
        # Look for "Role ARN: arn:aws:sts::..." in output
        for line in stdout.split("\n"):
            if "Role ARN:" in line and "arn:aws:" in line:
                try:
                    arn = line.split("Role ARN:")[1].strip()
                    return arn
                except IndexError:
                    pass
        return None

    def verify_all_participants(
        self, participants: List[Dict], parallel: int = 1
    ) -> List[VerificationResult]:
        """
        Verify all workshop participants in parallel.

        Args:
            participants: List of participant dicts
            parallel: Number of parallel verifications (1 = sequential)

        Returns:
            List of VerificationResult objects
        """
        results = []

        if parallel == 1:
            # Sequential execution
            for participant in participants:
                result = self.verify_participant(participant)
                results.append(result)
        else:
            # Parallel execution
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                future_to_participant = {
                    executor.submit(self.verify_participant, p): p for p in participants
                }

                for future in as_completed(future_to_participant):
                    result = future.result()
                    results.append(result)

        return results


def print_summary(results: List[VerificationResult]):
    """Print human-readable summary of verification results."""
    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)

    total = len(results)
    passed = sum(1 for r in results if r.success)
    failed = total - passed

    print(f"\nTotal Participants: {total}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")

    print("\n" + "-" * 80)
    print("DETAILED RESULTS")
    print("-" * 80)

    for result in sorted(results, key=lambda r: r.participant):
        status = "✅ PASS" if result.success else "❌ FAIL"
        print(f"\n{result.participant} ({result.instance_id}): {status}")
        print(f"  Tests Passed: {result.tests_passed}/{result.tests_total}")

        if result.role_arn:
            print(f"  Role ARN: {result.role_arn}")

        if result.error_message:
            print(f"  Error: {result.error_message[:200]}")

        print(f"  Execution Time: {result.execution_time_seconds:.1f}s")

    print("\n" + "=" * 80)

    if failed == 0:
        print("✅ All participants passed verification!")
        print("\nClaude Code CLI is ready for workshop deployment.")
    else:
        print(f"❌ {failed} participant(s) failed verification")
        print("\nReview error messages above for troubleshooting.")


def export_json_report(results: List[VerificationResult], output_file: str):
    """Export verification results to JSON file."""
    report = {
        "workshop_verification": {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "total_participants": len(results),
            "passed": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
            "results": [asdict(r) for r in results],
        }
    }

    with open(output_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n📄 JSON report saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Verify AWS Bedrock access for all workshop participants",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify all participants in workshop-2026-01
  python3 verify-bedrock-access-all-participants.py --workshop-id workshop-2026-01

  # Verify specific participants only
  python3 verify-bedrock-access-all-participants.py \\
    --workshop-id workshop-2026-01 \\
    --participants scientist1,scientist3

  # Parallel execution for faster verification
  python3 verify-bedrock-access-all-participants.py \\
    --workshop-id workshop-2026-01 \\
    --parallel 5

  # Generate JSON report
  python3 verify-bedrock-access-all-participants.py \\
    --workshop-id workshop-2026-01 \\
    --output-format json \\
    --output-file verification-report.json
        """,
    )

    parser.add_argument(
        "--workshop-id",
        required=True,
        help="Workshop ID (e.g., workshop-2026-01)",
    )

    parser.add_argument(
        "--participants",
        help="Comma-separated list of specific participants to verify (optional)",
    )

    parser.add_argument(
        "--region",
        default="us-west-2",
        help="AWS region (default: us-west-2)",
    )

    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Number of parallel verifications (default: 1 = sequential)",
    )

    parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    parser.add_argument(
        "--output-file",
        help="Output file path for JSON report (only with --output-format json)",
    )

    args = parser.parse_args()

    # Parse specific participants
    specific_participants = None
    if args.participants:
        specific_participants = [p.strip() for p in args.participants.split(",")]

    print(f"🔍 Verifying Bedrock access for workshop: {args.workshop_id}")
    print(f"   Region: {args.region}")

    if specific_participants:
        print(f"   Participants: {', '.join(specific_participants)}")
    else:
        print("   Participants: All")

    print(f"   Parallel: {args.parallel}")
    print()

    # Initialize verifier
    verifier = WorkshopVerifier(workshop_id=args.workshop_id, region=args.region)

    # Get participants
    try:
        participants = verifier.get_workshop_participants(specific_participants)
    except Exception as e:
        print(f"❌ ERROR: Cannot retrieve workshop participants: {e}")
        sys.exit(2)

    if not participants:
        print(
            f"❌ ERROR: No participants found for workshop {args.workshop_id}"
        )
        print("\nTroubleshooting:")
        print("  1. Verify workshop ID is correct")
        print("  2. Check DynamoDB table 'adept-workshop-deployments' exists")
        print("  3. Verify CloudFormation stacks follow naming pattern: ADE-{env}-{user}-Stack")
        sys.exit(2)

    print(f"Found {len(participants)} participant(s) to verify\n")

    # Run verification
    results = verifier.verify_all_participants(participants, parallel=args.parallel)

    # Output results
    if args.output_format == "json":
        if not args.output_file:
            print("❌ ERROR: --output-file required with --output-format json")
            sys.exit(1)

        export_json_report(results, args.output_file)
        print_summary(results)  # Still print text summary
    else:
        print_summary(results)

    # Exit with appropriate code
    failed_count = sum(1 for r in results if not r.success)
    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
