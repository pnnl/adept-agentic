#!/usr/bin/env python3
"""
Analyze validation log file for systematic error categorization and remediation planning.
"""

import re
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple
import sys

class ValidationLogAnalyzer:
    def __init__(self, log_file: str):
        self.log_file = Path(log_file)
        self.errors = defaultdict(list)
        self.failures = defaultdict(list)
        self.setup_errors = []
        self.collection_errors = []
        self.passed_tests = []
        self.validation_suites = {}
        
    def parse_log(self):
        """Parse the validation log file and categorize errors."""
        with open(self.log_file, 'r') as f:
            content = f.read()
            
        # Extract validation suite sections
        suite_pattern = r'=+ Running (.+?) =+'
        suites = re.findall(suite_pattern, content)
        
        # Split content by validation suites
        sections = re.split(r'=+ Running .+? =+', content)
        
        for i, suite in enumerate(suites):
            if i + 1 < len(sections):
                self.validation_suites[suite] = sections[i + 1]
                
        # Parse each section for errors
        self._parse_pytest_output(content)
        self._parse_setup_errors(content)
        self._parse_collection_errors(content)
        self._parse_docker_issues(content)
        self._parse_authentication_errors(content)
        
    def _parse_pytest_output(self, content: str):
        """Parse pytest output for failures and errors."""
        # Find FAILED tests
        failed_pattern = r'FAILED (.+?)(?:\[.+?\])? - (.+?)(?:\n|$)'
        for match in re.finditer(failed_pattern, content):
            test_name = match.group(1).strip()
            error_msg = match.group(2).strip()
            self.failures[test_name].append(error_msg)
            
        # Find ERROR tests
        error_pattern = r'ERROR (.+?) - (.+?)(?:\n|$)'
        for match in re.finditer(error_pattern, content):
            test_name = match.group(1).strip()
            error_msg = match.group(2).strip()
            self.errors[test_name].append(error_msg)
            
        # Find PASSED tests
        passed_pattern = r'PASSED (.+?)(?:\[.+?\])?(?:\n|$)'
        for match in re.finditer(passed_pattern, content):
            test_name = match.group(1).strip()
            if test_name not in self.passed_tests:
                self.passed_tests.append(test_name)
                
    def _parse_setup_errors(self, content: str):
        """Parse setup errors."""
        setup_error_pattern = r'ERROR at setup of (.+?)\n((?:.*?\n){1,20}?)(?:=|_)'
        for match in re.finditer(setup_error_pattern, content, re.MULTILINE):
            test_name = match.group(1).strip()
            error_detail = match.group(2).strip()
            self.setup_errors.append({
                'test': test_name,
                'error': error_detail[:500]  # Truncate long errors
            })
            
    def _parse_collection_errors(self, content: str):
        """Parse collection errors."""
        collection_pattern = r'ERROR collecting (.+?)\n((?:.*?\n){1,10}?)(?:=|_)'
        for match in re.finditer(collection_pattern, content, re.MULTILINE):
            file_name = match.group(1).strip()
            error_detail = match.group(2).strip()
            self.collection_errors.append({
                'file': file_name,
                'error': error_detail[:500]
            })
            
    def _parse_docker_issues(self, content: str):
        """Parse Docker-related issues."""
        docker_patterns = [
            r'docker\.errors\.NotFound: (.+)',
            r'requests\.exceptions\.ConnectionError.*docker',
            r'Cannot connect to Docker',
            r'Container .+ not found'
        ]
        
        docker_issues = []
        for pattern in docker_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                docker_issues.append(match.group(0))
                
        if docker_issues:
            self.errors['docker_connectivity'] = docker_issues
            
    def _parse_authentication_errors(self, content: str):
        """Parse authentication-related errors."""
        auth_patterns = [
            r'401 Unauthorized',
            r'Authentication failed',
            r'Invalid token',
            r'KeycloakAuthenticationError',
            r'JWT.*invalid'
        ]
        
        auth_issues = []
        for pattern in auth_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                auth_issues.append(match.group(0))
                
        if auth_issues:
            self.errors['authentication'] = auth_issues
            
    def categorize_errors(self) -> Dict:
        """Categorize errors by type for remediation."""
        categories = {
            'setup_failures': [],
            'import_errors': [],
            'connection_errors': [],
            'authentication_errors': [],
            'assertion_failures': [],
            'timeout_errors': [],
            'file_not_found': [],
            'docker_issues': [],
            'other': []
        }
        
        # Categorize setup errors
        for error in self.setup_errors:
            error_text = error['error'].lower()
            if 'import' in error_text or 'modulenotfounderror' in error_text:
                categories['import_errors'].append(error)
            elif 'connection' in error_text or 'refused' in error_text:
                categories['connection_errors'].append(error)
            elif 'timeout' in error_text:
                categories['timeout_errors'].append(error)
            else:
                categories['setup_failures'].append(error)
                
        # Categorize collection errors
        for error in self.collection_errors:
            error_text = error['error'].lower()
            if 'import' in error_text or 'modulenotfounderror' in error_text:
                categories['import_errors'].append(error)
            elif 'filenotfounderror' in error_text:
                categories['file_not_found'].append(error)
            else:
                categories['other'].append(error)
                
        # Add Docker issues
        if 'docker_connectivity' in self.errors:
            categories['docker_issues'] = self.errors['docker_connectivity']
            
        # Add authentication errors
        if 'authentication' in self.errors:
            categories['authentication_errors'] = self.errors['authentication']
            
        # Categorize test failures
        for test, errors in self.failures.items():
            for error in errors:
                error_lower = error.lower()
                if 'assert' in error_lower:
                    categories['assertion_failures'].append({'test': test, 'error': error})
                elif 'timeout' in error_lower:
                    categories['timeout_errors'].append({'test': test, 'error': error})
                else:
                    categories['other'].append({'test': test, 'error': error})
                    
        return categories
    
    def generate_remediation_plan(self, categories: Dict) -> Dict:
        """Generate remediation plan for each error category."""
        remediation = {}
        
        if categories['import_errors']:
            # Extract unique missing modules
            missing_modules = set()
            for error in categories['import_errors']:
                error_text = error.get('error', '')
                # Look for ModuleNotFoundError patterns
                module_match = re.search(r"No module named '([^']+)'", error_text)
                if module_match:
                    missing_modules.add(module_match.group(1))
                    
            remediation['import_errors'] = {
                'issue': f"Missing {len(missing_modules)} Python modules",
                'affected_files': [e.get('file', e.get('test', 'unknown')) for e in categories['import_errors'][:5]],
                'missing_modules': list(missing_modules),
                'actions': [
                    'Check if modules are in requirements.txt',
                    'Verify Docker image builds include all dependencies',
                    'Check for typos in import statements',
                    'Ensure test files have proper __init__.py files'
                ]
            }
            
        if categories['connection_errors']:
            remediation['connection_errors'] = {
                'issue': 'Service connectivity issues',
                'count': len(categories['connection_errors']),
                'actions': [
                    'Verify all services are running: make status',
                    'Check Docker network connectivity',
                    'Verify service URLs in .env files',
                    'Check if services are healthy: docker ps',
                    'Restart services: make restart'
                ]
            }
            
        if categories['authentication_errors']:
            remediation['authentication_errors'] = {
                'issue': 'Authentication/authorization failures',
                'count': len(categories['authentication_errors']),
                'actions': [
                    'Verify Keycloak is running and configured',
                    'Check service credentials: make validate-credentials',
                    'Fix credential drift: make fix-credentials',
                    'Verify JWT tokens are being generated correctly',
                    'Check RBAC group configurations'
                ]
            }
            
        if categories['docker_issues']:
            remediation['docker_issues'] = {
                'issue': 'Docker connectivity or container issues',
                'count': len(categories['docker_issues']),
                'actions': [
                    'Verify Docker daemon is running',
                    'Check Docker permissions for current user',
                    'Ensure containers are built: make rebuild',
                    'Check container health: docker ps -a',
                    'Review Docker Compose logs: docker compose logs'
                ]
            }
            
        if categories['timeout_errors']:
            remediation['timeout_errors'] = {
                'issue': 'Test timeouts',
                'count': len(categories['timeout_errors']),
                'actions': [
                    'Increase test timeout values',
                    'Check if services are responding slowly',
                    'Verify network latency',
                    'Check resource constraints (CPU/memory)',
                    'Consider running tests sequentially instead of in parallel'
                ]
            }
            
        if categories['file_not_found']:
            remediation['file_not_found'] = {
                'issue': 'Missing files or directories',
                'count': len(categories['file_not_found']),
                'actions': [
                    'Verify all required files are present',
                    'Check file paths are correct',
                    'Ensure volume mounts are configured correctly',
                    'Verify working directory is correct',
                    'Check file permissions'
                ]
            }
            
        if categories['assertion_failures']:
            remediation['assertion_failures'] = {
                'issue': 'Test assertion failures',
                'count': len(categories['assertion_failures']),
                'sample_failures': categories['assertion_failures'][:3],
                'actions': [
                    'Review test expectations vs actual behavior',
                    'Check if recent code changes broke tests',
                    'Verify test data is correct',
                    'Check for race conditions in async tests',
                    'Review service responses for schema changes'
                ]
            }
            
        return remediation
    
    def generate_summary_report(self) -> str:
        """Generate a comprehensive summary report."""
        categories = self.categorize_errors()
        remediation = self.generate_remediation_plan(categories)
        
        report = []
        report.append("=" * 80)
        report.append("VALIDATION LOG ANALYSIS REPORT")
        report.append("=" * 80)
        report.append("")
        
        # Overall statistics
        total_errors = sum(len(v) for v in categories.values())
        report.append("OVERALL STATISTICS:")
        report.append(f"  - Total Passed Tests: {len(self.passed_tests)}")
        report.append(f"  - Total Failed Tests: {len(self.failures)}")
        report.append(f"  - Total Setup Errors: {len(self.setup_errors)}")
        report.append(f"  - Total Collection Errors: {len(self.collection_errors)}")
        report.append(f"  - Total Categorized Issues: {total_errors}")
        report.append("")
        
        # Validation suites summary
        report.append("VALIDATION SUITES ANALYZED:")
        for suite in self.validation_suites.keys():
            report.append(f"  - {suite}")
        report.append("")
        
        # Error categories breakdown
        report.append("ERROR CATEGORIES BREAKDOWN:")
        for category, errors in categories.items():
            if errors:
                report.append(f"  - {category}: {len(errors)} issues")
        report.append("")
        
        # Remediation plan
        report.append("=" * 80)
        report.append("REMEDIATION PLAN")
        report.append("=" * 80)
        report.append("")
        
        priority_order = [
            'docker_issues',
            'connection_errors', 
            'authentication_errors',
            'import_errors',
            'file_not_found',
            'timeout_errors',
            'assertion_failures'
        ]
        
        for priority, category in enumerate(priority_order, 1):
            if category in remediation:
                plan = remediation[category]
                report.append(f"PRIORITY {priority}: {category.upper().replace('_', ' ')}")
                report.append("-" * 40)
                report.append(f"Issue: {plan['issue']}")
                if 'count' in plan:
                    report.append(f"Count: {plan['count']}")
                if 'missing_modules' in plan:
                    report.append(f"Missing Modules: {', '.join(plan['missing_modules'][:5])}")
                if 'affected_files' in plan:
                    report.append(f"Affected Files (sample): {', '.join(plan['affected_files'][:3])}")
                    
                report.append("\nRecommended Actions:")
                for i, action in enumerate(plan['actions'], 1):
                    report.append(f"  {i}. {action}")
                report.append("")
                
        # Quick fix commands
        report.append("=" * 80)
        report.append("QUICK FIX COMMANDS")
        report.append("=" * 80)
        report.append("")
        report.append("# Step 1: Ensure services are running")
        report.append("make restart")
        report.append("")
        report.append("# Step 2: Fix authentication issues")
        report.append("make fix-credentials")
        report.append("")
        report.append("# Step 3: Rebuild affected services")
        report.append("make rebuild")
        report.append("")
        report.append("# Step 4: Run validation again")
        report.append("make validate")
        report.append("")
        
        return "\n".join(report)

def main():
    if len(sys.argv) != 2:
        print("Usage: python analyze_validation_log.py <log_file>")
        sys.exit(1)
        
    log_file = sys.argv[1]
    if not Path(log_file).exists():
        print(f"Error: Log file '{log_file}' not found")
        sys.exit(1)
        
    analyzer = ValidationLogAnalyzer(log_file)
    analyzer.parse_log()
    report = analyzer.generate_summary_report()
    
    print(report)
    
    # Also save to file
    output_file = Path(log_file).with_suffix('.analysis.txt')
    with open(output_file, 'w') as f:
        f.write(report)
    print(f"\nAnalysis saved to: {output_file}")

if __name__ == "__main__":
    main()