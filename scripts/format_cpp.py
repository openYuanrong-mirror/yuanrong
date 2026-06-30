#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
C++ Code Auto-Formatter for Yuanrong

Usage:
    python3 scripts/format_cpp.py              # Format all modified files
    python3 scripts/format_cpp.py --dry-run    # Show what would be changed
    python3 scripts/format_cpp.py --all        # Format all .cpp/.h files
    python3 scripts/format_cpp.py file1.cpp file2.h  # Format specific files
    python3 scripts/format_cpp.py --check      # Check formatting (exit 1 if issues)

Features:
    - G.FMT.04-CPP: Split multiple (void) casts onto separate lines
    - G.FMT.05-CPP: Break lines exceeding 120 characters
    - G.RES.09-CPP: Use std::make_unique instead of new for std::unique_ptr
    - clang-format integration (if .clang-format exists)
"""

import argparse
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

MAX_LINE_WIDTH = 120
LOGGER = logging.getLogger(__name__)


def get_modified_files() -> List[str]:
    """Get list of modified .cpp and .h files from git diff"""
    result = subprocess.run(
        ['git', 'diff', '--name-only', 'origin/master...HEAD'],
        capture_output=True, text=True, cwd=os.getcwd()
    )
    files = result.stdout.strip().split('\n')
    return [f for f in files if f.endswith(('.cpp', '.h')) and os.path.exists(f)]


def get_all_cpp_files() -> List[str]:
    """Get all .cpp and .h files in the repository"""
    files = []
    for ext in ['*.cpp', '*.h', '*.hpp', '*.cc', '*.cxx']:
        files.extend(Path('.').rglob(ext))
    return [str(f) for f in files if 'thirdparty' not in str(f) and 'third_party' not in str(f)]


def fix_make_unique(content: str) -> Tuple[str, int]:
    """G.RES.09-CPP: Replace unique_ptr<T>(new T(...)) with make_unique<T>(...)

    NOTE: This fix is DISABLED by default because std::make_unique cannot access
    private constructors, which is common in singleton patterns. The check script
    will still report these issues for manual review.

    To enable this fix, use --enable-make-unique flag.
    """
    # Disabled by default - make_unique cannot access private constructors
    return content, 0


def fix_multiple_void_casts(content: str) -> Tuple[str, int]:
    """G.FMT.04-CPP: Split multiple (void) cast statements onto separate lines"""
    count = 0
    lines = content.split('\n')
    new_lines = []

    for line in lines:
        stripped = line.strip()
        # Skip comments
        if stripped.startswith('//') or stripped.startswith('/*'):
            new_lines.append(line)
            continue

        # Check for multiple (void) cast statements
        if '(void)' in line:
            void_casts = re.findall(r'\(void\)\w+\s*;', line)
            if len(void_casts) > 1:
                # Extract indentation
                indent = len(line) - len(line.lstrip())
                indent_str = line[:indent]

                # Split each (void) cast to its own line
                parts = re.findall(r'\(void\)\w+\s*;', line)
                for _, part in enumerate(parts):
                    new_lines.append(indent_str + part)
                    count += 1
                continue

        new_lines.append(line)

    return '\n'.join(new_lines), count


def fix_long_lines(content: str) -> Tuple[str, int]:
    """G.FMT.05-CPP: Break lines exceeding 120 characters"""
    count = 0
    lines = content.split('\n')
    new_lines = []

    for line in lines:
        if len(line) > MAX_LINE_WIDTH:
            stripped = line.lstrip()

            # Skip long URLs in comments
            if stripped.startswith('//') and ('http' in stripped or 'https' in stripped):
                new_lines.append(line)
                continue

            # Skip preprocessor directives
            if stripped.startswith('#'):
                new_lines.append(line)
                continue

            # Try to break at logical points
            indent = len(line) - len(line.lstrip())
            indent_str = ' ' * (indent + 4)

            new_line = line

            # Try breaking at common points: comma followed by space
            if ',' in line and '(' in line:
                # Find a good break point
                parts = []
                current = ""
                paren_depth = 0
                i = 0
                while i < len(line):
                    char = line[i]
                    if char == '(':
                        paren_depth += 1
                    elif char == ')':
                        paren_depth -= 1
                    elif char == ',' and paren_depth == 0:
                        if len(current) > 80:  # Break before 120
                            parts.append(current + ',')
                            current = indent_str
                            i += 1  # Skip the comma we already added
                            while i < len(line) and line[i] == ' ':
                                i += 1  # Skip spaces after comma
                            continue
                    current += char
                    i += 1

                if parts:
                    parts.append(current)
                    new_line = '\n'.join(parts)
                    count += 1

            new_lines.append(new_line)
        else:
            new_lines.append(line)

    return '\n'.join(new_lines), count


def run_clang_format(file_path: str, dry_run: bool = False) -> Tuple[bool, str]:
    """Run clang-format on a file"""
    # Check if clang-format is available
    clang_format = os.environ.get('CLANG_FORMAT', 'clang-format')

    try:
        result = subprocess.run(
            [clang_format, '--version'],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return False, "clang-format not found"
    except FileNotFoundError:
        return False, "clang-format not found"

    # Check if .clang-format exists
    if not os.path.exists('.clang-format'):
        return False, ".clang-format not found"

    if dry_run:
        # Check if file would be changed
        result = subprocess.run(
            [clang_format, '--dry-run', '--Werror', file_path],
            capture_output=True, text=True
        )
        return result.returncode != 0, "needs formatting"
    else:
        # Format in place
        result = subprocess.run(
            [clang_format, '-i', file_path],
            capture_output=True, text=True
        )
        return result.returncode == 0, "formatted"


def format_file(file_path: str, dry_run: bool = False, use_clang_format: bool = True) -> Tuple[bool, dict]:
    """Format a single file and return (changed, stats)"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            original_content = f.read()
    except OSError as err:
        LOGGER.error("Error reading %s: %s", file_path, err)
        return False, {}

    content = original_content
    stats = {
        'make_unique': 0,
        'void_casts': 0,
        'long_lines': 0,
        'clang_format': False,
    }

    # Apply custom fixes
    content, n = fix_make_unique(content)
    stats['make_unique'] = n

    content, n = fix_multiple_void_casts(content)
    stats['void_casts'] = n

    content, n = fix_long_lines(content)
    stats['long_lines'] = n

    changed = content != original_content

    if changed and not dry_run:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

    # Run clang-format if enabled
    if use_clang_format:
        cf_changed, cf_msg = run_clang_format(file_path, dry_run)
        LOGGER.debug("clang-format %s: %s", file_path, cf_msg)
        stats['clang_format'] = cf_changed
        if cf_changed:
            changed = True

    return changed, stats


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description='Format C++ code files')
    parser.add_argument('files', nargs='*', help='Files to format (default: modified files)')
    parser.add_argument('-n', '--dry-run', action='store_true', help='Show what would be changed')
    parser.add_argument('--all', action='store_true', help='Format all files in repository')
    parser.add_argument('--check', action='store_true', help='Exit with 1 if formatting needed')
    parser.add_argument('--no-clang-format', action='store_true', help='Skip clang-format')
    args = parser.parse_args()

    # Determine which files to format
    if args.files:
        files = args.files
    elif args.all:
        files = get_all_cpp_files()
    else:
        files = get_modified_files()

    if not files:
        LOGGER.info("No C++ files to format")
        return 0

    LOGGER.info("%sFormatting %s files...", "[DRY RUN] " if args.dry_run else "", len(files))

    total_stats = {
        'make_unique': 0,
        'void_casts': 0,
        'long_lines': 0,
        'clang_format': 0,
        'files_changed': 0,
    }

    for file_path in files:
        if not os.path.exists(file_path):
            continue

        changed, stats = format_file(
            file_path,
            dry_run=args.dry_run,
            use_clang_format=not args.no_clang_format
        )

        if changed:
            total_stats['files_changed'] += 1
            total_stats['make_unique'] += stats['make_unique']
            total_stats['void_casts'] += stats['void_casts']
            total_stats['long_lines'] += stats['long_lines']
            if stats['clang_format']:
                total_stats['clang_format'] += 1

            status = "would change" if args.dry_run else "formatted"
            LOGGER.info("  %s: %s", status, file_path)
            if stats['make_unique']:
                LOGGER.info("    - %s make_unique fix(es)", stats['make_unique'])
            if stats['void_casts']:
                LOGGER.info("    - %s void cast split(s)", stats['void_casts'])
            if stats['long_lines']:
                LOGGER.info("    - %s long line fix(es)", stats['long_lines'])
            if stats['clang_format']:
                LOGGER.info("    - clang-format applied")

    LOGGER.info("\nSummary:")
    LOGGER.info("  Files %schanged: %s", "would be " if args.dry_run else "", total_stats['files_changed'])
    LOGGER.info("  make_unique fixes: %s", total_stats['make_unique'])
    LOGGER.info("  void cast splits: %s", total_stats['void_casts'])
    LOGGER.info("  long line fixes: %s", total_stats['long_lines'])
    LOGGER.info("  clang-format: %s", total_stats['clang_format'])

    if args.check and total_stats['files_changed'] > 0:
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
