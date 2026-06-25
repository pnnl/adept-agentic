"""
Pre-execution security validation for generated code.

This module provides comprehensive security analysis to prevent execution of 
potentially dangerous code including:
- System command execution (rm, curl, wget, etc.)
- Dangerous imports (subprocess, os.system, etc.)  
- Network access attempts
- File system traversal attacks
"""

import ast
import re
from typing import Tuple, List, Set, Dict, Any
from dataclasses import dataclass
from enum import Enum

from ...logger_config import get_logger

logger = get_logger(__name__)

class RiskLevel(Enum):
    """Security risk levels for code execution."""
    LOW = "low"
    MEDIUM = "medium"  
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class SecurityViolation:
    """Represents a security violation found in code."""
    type: str
    message: str
    line_number: int = None
    risk_level: RiskLevel = RiskLevel.MEDIUM
    suggested_action: str = None

class CodeSecurityValidator:
    """Comprehensive pre-execution security validator for Python code."""
    
    # Critical imports that allow system access
    # NOTE: In medium/permissive mode, only CRITICAL blocks execution.
    # HIGH generates warnings but allows execution (needed for license servers, HPC).
    # Submodule imports also matched (e.g., "docker.api" → checks "docker" base).
    # Docker socket paths blocked by PATH_TRAVERSAL_PATTERNS at CRITICAL (literal regex).
    # NOTE: regex path detection is bypassable via dynamic string construction;
    # primary defense is socket NOT MOUNTED (docker-compose.core.yaml default).
    # Compensating controls:
    #   CC-SANDBOX-01: Network egress allowed (PNNL license servers, HPC)
    #   CC-SANDBOX-02: No nsjail — validator is primary defense layer
    # Ref: docs/security/SANDBOX_EXECUTION_METHOD_SECURITY.md §7
    DANGEROUS_IMPORTS = {
        'subprocess': RiskLevel.CRITICAL,
        'os': RiskLevel.HIGH,  # os.system, os.popen flagged separately as CRITICAL functions
        'sys': RiskLevel.MEDIUM,  # sys.exit might be okay
        'socket': RiskLevel.HIGH,  # Network access needed for license servers, HPC
        'urllib': RiskLevel.HIGH,  # HTTP access (egress controlled by network policy)
        'requests': RiskLevel.HIGH,  # HTTP access (egress controlled by network policy)
        'http': RiskLevel.HIGH,  # http.client — Docker socket path blocked by PATH_TRAVERSAL
        'ftplib': RiskLevel.CRITICAL,
        'smtplib': RiskLevel.CRITICAL,
        'telnetlib': RiskLevel.CRITICAL,
        'paramiko': RiskLevel.CRITICAL,
        'fabric': RiskLevel.CRITICAL,
        'psutil': RiskLevel.HIGH,  # Process/system info
        'shutil': RiskLevel.MEDIUM,  # File operations
        'docker': RiskLevel.CRITICAL,  # Docker SDK — container escape
        'dockerpty': RiskLevel.CRITICAL,  # Docker PTY — container escape
    }
    
    # Dangerous function calls
    DANGEROUS_FUNCTIONS = {
        'os.system': RiskLevel.CRITICAL,
        'os.popen': RiskLevel.CRITICAL,
        'os.spawn': RiskLevel.CRITICAL,
        'subprocess.run': RiskLevel.CRITICAL,
        'subprocess.call': RiskLevel.CRITICAL,
        'subprocess.Popen': RiskLevel.CRITICAL,
        'subprocess.check_output': RiskLevel.CRITICAL,
        'eval': RiskLevel.CRITICAL,
        'exec': RiskLevel.CRITICAL,
        '__import__': RiskLevel.HIGH,
        'compile': RiskLevel.HIGH,
        'globals': RiskLevel.MEDIUM,
        'locals': RiskLevel.MEDIUM,
        'vars': RiskLevel.MEDIUM,
    }
    
    # Dangerous shell command patterns
    DANGEROUS_SHELL_PATTERNS = {
        r'rm\s+-rf': RiskLevel.CRITICAL,
        r'rm\s+.*\*': RiskLevel.CRITICAL,
        r'curl\s+.*\|': RiskLevel.CRITICAL,  # Curl piped to shell
        r'wget\s+.*\|': RiskLevel.CRITICAL,  # Wget piped to shell
        r'nc\s+.*': RiskLevel.HIGH,  # Netcat
        r'netcat\s+.*': RiskLevel.HIGH,
        r'ssh\s+.*': RiskLevel.HIGH,
        r'scp\s+.*': RiskLevel.HIGH,
        r'rsync\s+.*': RiskLevel.HIGH,
        r'dd\s+.*': RiskLevel.HIGH,  # Disk operations
        r'mkfs\s+.*': RiskLevel.CRITICAL,  # Format filesystem
        r'fdisk\s+.*': RiskLevel.CRITICAL,
        r'mount\s+.*': RiskLevel.HIGH,
        r'umount\s+.*': RiskLevel.HIGH,
        r'chmod\s+777': RiskLevel.MEDIUM,  # Overly permissive
        r'chown\s+.*': RiskLevel.MEDIUM,
    }
    
    # File path patterns indicating traversal attempts
    PATH_TRAVERSAL_PATTERNS = {
        r'\.\.\/': RiskLevel.CRITICAL,  # Path traversal is critical security issue
        r'\.\.\\': RiskLevel.CRITICAL,  # Path traversal is critical security issue
        r'\/etc\/': RiskLevel.CRITICAL,
        r'\/proc\/': RiskLevel.CRITICAL,
        r'\/sys\/': RiskLevel.CRITICAL,
        r'\/dev\/': RiskLevel.CRITICAL,
        r'\/root\/': RiskLevel.CRITICAL,
        r'\/home\/[^\/]+\/\.ssh': RiskLevel.CRITICAL,
        r'\/var\/log\/': RiskLevel.MEDIUM,
        r'\/var\/run\/docker': RiskLevel.CRITICAL,  # Docker socket privilege escalation
        r'docker\.sock': RiskLevel.CRITICAL,  # Docker socket access (any path)
        r'\/run\/docker': RiskLevel.CRITICAL,  # Alternative Docker socket path
    }
    
    # Allowed imports for scientific computing (whitelist approach)
    ALLOWED_IMPORTS = {
        # Data science core
        'numpy', 'pandas', 'matplotlib', 'seaborn', 'plotly', 'scipy', 'sklearn',
        'scikit-learn', 'statsmodels', 'sympy', 'networkx',
        
        # Standard library (safe subset)
        'math', 'statistics', 'random', 'datetime', 'time', 'json', 'csv', 
        'io', 'pathlib', 'collections', 'itertools', 'functools', 'operator',
        'copy', 'pickle', 'base64', 'hashlib', 'uuid', 'logging',
        
        # Visualization and output
        'PIL', 'Pillow', 'cv2', 'skimage', 'bokeh', 'altair',
        
        # Machine learning
        'torch', 'pytorch', 'tensorflow', 'keras', 'xgboost', 'lightgbm',
        'catboost', 'transformers', 'datasets', 'accelerate',
        
        # Bioinformatics/Chemistry (if relevant)
        'Bio', 'rdkit', 'chempy', 'pubchempy',
        
        # Configuration/typing
        'typing', 'dataclasses', 'enum', 'pydantic', 'configparser',
        're', 'string', 'textwrap'
    }

    def __init__(self, strict_mode: bool = True, allow_file_access: bool = True):
        """
        Initialize the security validator.
        
        Args:
            strict_mode: If True, uses whitelist approach for imports
            allow_file_access: If True, allows basic file I/O operations
        """
        self.strict_mode = strict_mode
        self.allow_file_access = allow_file_access
        
    def validate_code(self, code: str, session_id: str = None) -> Tuple[bool, List[SecurityViolation]]:
        """
        Perform comprehensive security validation of Python code.
        
        Args:
            code: Python code to validate
            session_id: Optional session identifier for logging
            
        Returns:
            Tuple of (is_safe, violations_list)
        """
        violations = []
        
        try:
            # 1. AST-based analysis for imports and function calls
            violations.extend(self._analyze_ast(code))
            
            # 2. String-based pattern analysis  
            violations.extend(self._analyze_string_patterns(code))
            
            # 3. Check for path traversal attempts
            violations.extend(self._analyze_path_traversal(code))
            
            # 4. Analyze file operations if restricted
            if not self.allow_file_access:
                violations.extend(self._analyze_file_operations(code))
                
        except SyntaxError as e:
            violations.append(SecurityViolation(
                type="syntax_error",
                message=f"Code contains syntax errors: {e}",
                line_number=e.lineno,
                risk_level=RiskLevel.MEDIUM,
                suggested_action="Fix syntax errors before execution"
            ))
        except Exception as e:
            logger.error(f"Error during security validation: {e}")
            violations.append(SecurityViolation(
                type="validation_error", 
                message=f"Security validation failed: {e}",
                risk_level=RiskLevel.HIGH,
                suggested_action="Review code for potential issues"
            ))
        
        # Determine if code is safe based on violation risk levels
        critical_violations = [v for v in violations if v.risk_level == RiskLevel.CRITICAL]
        is_safe = len(critical_violations) == 0
        
        if session_id:
            logger.info(f"Security validation for session {session_id}: {len(violations)} violations, safe: {is_safe}")
            
        return is_safe, violations
    
    def _analyze_ast(self, code: str) -> List[SecurityViolation]:
        """Analyze code using AST parsing to detect dangerous patterns."""
        violations = []
        
        try:
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                # Check imports
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        violations.extend(self._check_import(alias.name, node.lineno))
                        
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        violations.extend(self._check_import(node.module, node.lineno))
                        
                # Check function calls
                elif isinstance(node, ast.Call):
                    violations.extend(self._check_function_call(node))
                    
                # Check attribute access (e.g., os.system)
                elif isinstance(node, ast.Attribute):
                    violations.extend(self._check_attribute_access(node))
                    
        except Exception as e:
            logger.warning(f"AST analysis failed: {e}")
            
        return violations
    
    def _check_import(self, module_name: str, line_no: int) -> List[SecurityViolation]:
        """Check if an import is safe."""
        violations = []
        
        if self.strict_mode:
            # Whitelist approach - only allow safe imports
            # Check if the base module or any parent module is allowed
            base_module = module_name.split('.')[0]
            is_allowed = (module_name in self.ALLOWED_IMPORTS or 
                         base_module in self.ALLOWED_IMPORTS or
                         any(module_name.startswith(allowed + '.') for allowed in self.ALLOWED_IMPORTS))
            
            if not is_allowed:
                violations.append(SecurityViolation(
                    type="disallowed_import",
                    message=f"Import '{module_name}' not in whitelist",
                    line_number=line_no,
                    risk_level=RiskLevel.CRITICAL,  # CRITICAL in strict mode blocks execution
                    suggested_action=f"Use approved scientific libraries only"
                ))
        else:
            # Blacklist approach - block dangerous imports
            # Check both exact match and base module (e.g., "docker.api" → "docker")
            base_module = module_name.split('.')[0]
            matched_module = None
            if module_name in self.DANGEROUS_IMPORTS:
                matched_module = module_name
            elif base_module in self.DANGEROUS_IMPORTS:
                matched_module = base_module
            if matched_module:
                violations.append(SecurityViolation(
                    type="dangerous_import",
                    message=f"Dangerous import detected: {module_name}",
                    line_number=line_no,
                    risk_level=self.DANGEROUS_IMPORTS[matched_module],
                    suggested_action=f"Replace with safe alternative or remove"
                ))
                
        return violations
    
    def _check_function_call(self, node: ast.Call) -> List[SecurityViolation]:
        """Check if a function call is dangerous."""
        violations = []
        
        # Get function name from various call types
        func_name = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                func_name = f"{node.func.value.id}.{node.func.attr}"
                
        if func_name and func_name in self.DANGEROUS_FUNCTIONS:
            violations.append(SecurityViolation(
                type="dangerous_function",
                message=f"Dangerous function call: {func_name}",
                line_number=node.lineno,
                risk_level=self.DANGEROUS_FUNCTIONS[func_name],
                suggested_action="Use safe alternatives for this operation"
            ))
            
        return violations
    
    def _check_attribute_access(self, node: ast.Attribute) -> List[SecurityViolation]:
        """Check dangerous attribute access patterns."""
        violations = []
        
        if isinstance(node.value, ast.Name):
            attr_access = f"{node.value.id}.{node.attr}"
            if attr_access in self.DANGEROUS_FUNCTIONS:
                violations.append(SecurityViolation(
                    type="dangerous_attribute",
                    message=f"Dangerous attribute access: {attr_access}",
                    line_number=node.lineno,
                    risk_level=self.DANGEROUS_FUNCTIONS[attr_access],
                    suggested_action="Avoid direct system access"
                ))
                
        return violations
    
    def _analyze_string_patterns(self, code: str) -> List[SecurityViolation]:
        """Analyze code for dangerous string patterns."""
        violations = []
        lines = code.split('\n')
        
        for line_no, line in enumerate(lines, 1):
            # Check for shell command patterns
            for pattern, risk_level in self.DANGEROUS_SHELL_PATTERNS.items():
                if re.search(pattern, line, re.IGNORECASE):
                    violations.append(SecurityViolation(
                        type="dangerous_shell_pattern",
                        message=f"Dangerous shell command pattern: {pattern}",
                        line_number=line_no,
                        risk_level=risk_level,
                        suggested_action="Avoid shell command execution"
                    ))
                    
        return violations
    
    def _analyze_path_traversal(self, code: str) -> List[SecurityViolation]:
        """Check for path traversal attempts."""
        violations = []
        lines = code.split('\n')
        
        for line_no, line in enumerate(lines, 1):
            for pattern, risk_level in self.PATH_TRAVERSAL_PATTERNS.items():
                if re.search(pattern, line):
                    violations.append(SecurityViolation(
                        type="path_traversal",
                        message=f"Potential path traversal: {pattern}",
                        line_number=line_no,
                        risk_level=risk_level,
                        suggested_action="Use safe file paths within sandbox"
                    ))
                    
        return violations
    
    def _analyze_file_operations(self, code: str) -> List[SecurityViolation]:
        """Check for file operations when disabled."""
        violations = []
        
        file_operation_patterns = [
            r'open\s*\(',
            r'file\s*\(',
            r'with\s+open',
            r'\.read\(',
            r'\.write\(',
            r'\.delete\(',
        ]
        
        lines = code.split('\n')
        for line_no, line in enumerate(lines, 1):
            for pattern in file_operation_patterns:
                if re.search(pattern, line):
                    violations.append(SecurityViolation(
                        type="file_operation",
                        message=f"File operation detected when disabled",
                        line_number=line_no,
                        risk_level=RiskLevel.MEDIUM,
                        suggested_action="File operations are restricted"
                    ))
                    
        return violations

def create_security_config(level: str = "medium") -> Dict[str, Any]:
    """
    Create security configuration for different protection levels.

    Levels:
        "strict": Import whitelist only (numpy, pandas, scipy, etc.). Blocks ALL
                  network, subprocess, and OS access. For maximum isolation.
        "medium": Import blacklist. Blocks subprocess, os.system, eval, exec.
                  Allows network imports (socket, urllib, requests) for license
                  servers and HPC connectivity. Docker socket paths still CRITICAL.
        "permissive": Same as medium. Exists for backward compatibility.

    Args:
        level: "strict", "medium", "permissive"

    Returns:
        Configuration dictionary for CodeSecurityValidator
    """
    configs = {
        "strict": {
            "strict_mode": True,
            "allow_file_access": False,
        },
        "medium": {
            "strict_mode": False,
            "allow_file_access": True,
        },
        "permissive": {
            "strict_mode": False,
            "allow_file_access": True,
        }
    }

    return configs.get(level, configs["medium"])