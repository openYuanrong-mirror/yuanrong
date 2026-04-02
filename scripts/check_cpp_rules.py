#!/usr/bin/env python3
"""
C++ Code Style Checker for Yuanrong
Checks the following rules:
- G.FMT.04-CPP: Each variable declaration/assignment on separate line
- G.FMT.05-CPP: Line width not exceeding 120 characters
- G.CLS.03-CPP: Single-argument constructors declared explicit
- G.RES.09-CPP: Use std::make_unique instead of new for std::unique_ptr
- G.FMT.03-CPP: Consistent brace style (Allman style)
- G.CNS.02: No magic numbers/literals
- G.CMT.03-CPP: File header contains copyright notice
- G.INC.07-CPP: Include headers in proper order
"""

import os
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Set

# Maximum line width
MAX_LINE_WIDTH = 120

# Copyright patterns
COPYRIGHT_PATTERNS = [
    r'Copyright',
    r'copyright',
    r'COPYRIGHT',
    r'华为',
    r'Huawei',
    r'HUAWEI',
]

class Issue:
    def __init__(self, file: str, line: int, rule: str, message: str):
        self.file = file
        self.line = line
        self.rule = rule
        self.message = message

    def __str__(self):
        return f"{self.file}:{self.line}: [{self.rule}] {self.message}"

def get_modified_files() -> List[str]:
    """Get list of modified .cpp and .h files from git diff"""
    result = subprocess.run(
        ['git', 'diff', '--name-only', 'origin/master...HEAD'],
        capture_output=True, text=True, cwd=os.getcwd()
    )
    files = result.stdout.strip().split('\n')
    return [f for f in files if f.endswith(('.cpp', '.h')) and os.path.exists(f)]

def check_line_width(lines: List[str], file_path: str) -> List[Issue]:
    """G.FMT.05-CPP: Check line width not exceeding 120 characters"""
    issues = []
    for i, line in enumerate(lines, 1):
        # Skip long URLs or paths in comments
        if len(line) > MAX_LINE_WIDTH:
            stripped = line.lstrip()
            # Allow long URLs in comments
            if stripped.startswith('//') and ('http' in stripped or 'https' in stripped):
                continue
            issues.append(Issue(file_path, i, "G.FMT.05-CPP",
                f"Line exceeds {MAX_LINE_WIDTH} characters ({len(line)} chars)"))
    return issues

def check_multiple_statements(lines: List[str], file_path: str) -> List[Issue]:
    """G.FMT.04-CPP: Check each variable declaration/assignment on separate line"""
    issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments and preprocessor directives
        if stripped.startswith('//') or stripped.startswith('#') or stripped.startswith('/*'):
            continue
        # Skip lines in strings or containing specific patterns
        if '"""' in stripped or "'''" in stripped:
            continue
        # Check for multiple (void) cast statements on same line
        void_casts = re.findall(r'\(void\)\w+\s*;', stripped)
        if len(void_casts) > 1:
            issues.append(Issue(file_path, i, "G.FMT.04-CPP",
                "Multiple (void) cast statements on same line, separate them"))
        # Check for multiple variable declarations on same line (excluding function parameters)
        # Pattern: type var1, var2; (but not in function signatures)
        if not re.search(r'[()]', stripped):
            # Check for declarations like: int a, b, c;
            decl_match = re.match(r'^(\w+\s+)+(\w+)\s*,\s*(\w+)', stripped)
            if decl_match and not stripped.startswith('return'):
                issues.append(Issue(file_path, i, "G.FMT.04-CPP",
                    "Multiple variable declarations on same line"))
    return issues

def check_explicit_constructor(lines: List[str], file_path: str) -> List[Issue]:
    """G.CLS.03-CPP: Single-argument constructors should be explicit"""
    issues = []
    in_class = False
    class_indent = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track class scope
        if re.match(r'(class|struct)\s+\w+', stripped):
            in_class = True
            class_indent = len(line) - len(line.lstrip())

        # Check for single-argument constructor without explicit
        # Pattern: ClassName(type param) or ClassName(type param = value)
        # But not: ClassName(type param1, type param2) - multi-arg
        # Also not: ~ClassName() - destructor
        # Also not: explicit ClassName(...) - already explicit

        # Match constructor with single parameter (without explicit keyword)
        # Look for patterns like:
        #   ClassName(Type param)
        #   ClassName(Type param = default)
        # but not:
        #   explicit ClassName(...)
        #   ClassName(Type1 p1, Type2 p2)

        if in_class:
            # Skip if already has explicit
            if 'explicit' in stripped:
                continue

            # Match constructor definition
            ctor_pattern = r'^(\w+)\s*\(\s*(?:const\s+)?(\w+(?:\s*[*&])?)\s+(\w+)(?:\s*=\s*[^)]+)?\s*\)'
            match = re.match(ctor_pattern, stripped)
            if match:
                class_name = match.group(1)
                param_type = match.group(2)
                # Check if this is indeed a constructor (class name matches)
                # and it's a single parameter
                # Skip copy/move constructors
                if param_type.strip() in [class_name, class_name + '&', class_name + '&&']:
                    continue
                issues.append(Issue(file_path, i, "G.CLS.03-CPP",
                    f"Single-argument constructor '{class_name}' should be declared explicit"))

    return issues

def check_make_unique(lines: List[str], file_path: str) -> List[Issue]:
    """G.RES.09-CPP: Use std::make_unique instead of new for std::unique_ptr"""
    issues = []
    for i, line in enumerate(lines, 1):
        # Check for unique_ptr<T>(new T(...))
        if 'unique_ptr' in line and 'new ' in line:
            # Pattern: std::unique_ptr<Type>(new Type(...))
            if re.search(r'unique_ptr\s*<[^>]+>\s*\(\s*new\s+', line):
                issues.append(Issue(file_path, i, "G.RES.09-CPP",
                    "Use std::make_unique instead of new for std::unique_ptr"))
    return issues

def check_brace_style(lines: List[str], file_path: str) -> List[Issue]:
    """G.FMT.03-CPP: Consistent brace style (Allman/K&R)"""
    issues = []
    # This is complex to check automatically, skip for now
    # The project seems to use K&R style mostly
    return issues

def check_magic_numbers(lines: List[str], file_path: str) -> List[Issue]:
    """G.CNS.02: No magic numbers/literals without explanation"""
    issues = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('/*'):
            continue

        # Check for magic numbers (but allow common cases)
        # Skip if line has a comment explaining the number
        if '//' in line:
            continue

        # Check for bare numbers that might be magic numbers
        # But skip common cases like array indices, 0, 1, -1, etc.
        numbers = re.findall(r'\b(\d{2,})\b', stripped)
        for num in numbers:
            # Skip common non-magic numbers
            if num in ['0', '1', '2', '10', '100', '1000']:
                continue
            # Skip hex numbers
            if stripped.lower().find(f'0x{num.lower()}') >= 0:
                continue
            # Skip if it's a size constant like 1024, 4096
            if num in ['1024', '2048', '4096', '8192', '65536']:
                continue
            # Skip if it's in a constant definition
            if 'const' in stripped or 'constexpr' in stripped or '#define' in stripped:
                continue

            # Check if there's no explanation nearby
            issues.append(Issue(file_path, i, "G.CNS.02",
                f"Potential magic number '{num}' without explanation"))
    return issues

def check_copyright_header(lines: List[str], file_path: str) -> List[Issue]:
    """G.CMT.03-CPP: File header contains copyright notice"""
    issues = []
    # Check first 20 lines for copyright
    header = '\n'.join(lines[:20])
    has_copyright = any(re.search(pattern, header) for pattern in COPYRIGHT_PATTERNS)

    if not has_copyright:
        issues.append(Issue(file_path, 1, "G.CMT.03-CPP",
            "File header missing copyright notice"))
    return issues

def check_include_order(lines: List[str], file_path: str) -> List[Issue]:
    """G.INC.07-CPP: Include headers in proper order"""
    issues = []
    includes = []
    include_start = -1

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('#include'):
            if include_start == -1:
                include_start = i
            includes.append((i, stripped))
        elif includes and stripped and not stripped.startswith('//') and not stripped.startswith('/*'):
            # End of include block
            break

    if not includes:
        return issues

    # Check order: should be
    # 1. Related header (for .cpp files)
    # 2. System headers <>
    # 3. Project headers ""

    prev_type = None
    prev_include = None

    for line_num, include in includes:
        is_system = include.find('<') > include.find('"') if '"' in include else '<' in include

        current_type = 'system' if is_system else 'project'

        # Check if project headers come before system headers (after first include)
        if prev_type == 'system' and current_type == 'project':
            # This might be okay for some projects, but generally discouraged
            issues.append(Issue(file_path, line_num, "G.INC.07-CPP",
                f"Project header '{include}' should come before system headers"))

        prev_type = current_type
        prev_include = include

    return issues

def check_file(file_path: str) -> List[Issue]:
    """Run all checks on a single file"""
    issues = []

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        return issues

    # Remove line endings for processing
    lines = [line.rstrip('\n\r') for line in lines]

    # Run all checks
    issues.extend(check_line_width(lines, file_path))
    issues.extend(check_multiple_statements(lines, file_path))
    issues.extend(check_explicit_constructor(lines, file_path))
    issues.extend(check_make_unique(lines, file_path))
    issues.extend(check_brace_style(lines, file_path))
    issues.extend(check_magic_numbers(lines, file_path))
    issues.extend(check_copyright_header(lines, file_path))
    issues.extend(check_include_order(lines, file_path))

    return issues

def main():
    # Get list of files to check
    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        files = get_modified_files()

    if not files:
        print("No C++ files to check")
        return 0

    print(f"Checking {len(files)} files...")

    all_issues = []
    for file_path in files:
        if os.path.exists(file_path):
            issues = check_file(file_path)
            all_issues.extend(issues)

    # Sort by file and line number
    all_issues.sort(key=lambda x: (x.file, x.line))

    # Print results
    if all_issues:
        print(f"\nFound {len(all_issues)} issues:\n")
        for issue in all_issues:
            print(str(issue))
        return 1
    else:
        print("\nNo issues found!")
        return 0

if __name__ == '__main__':
    sys.exit(main())
