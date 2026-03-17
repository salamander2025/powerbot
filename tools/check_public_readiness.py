#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from powerbot_core.public_release import scan_public_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description='Scan a PowerBot repo for publish-time privacy risks.')
    parser.add_argument('project_root', nargs='?', default=PROJECT_ROOT, type=Path)
    parser.add_argument('--json', action='store_true', dest='as_json')
    parser.add_argument('--strict', action='store_true', help='Exit non-zero on any warning.')
    args = parser.parse_args()

    report = scan_public_readiness(args.project_root)
    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for finding in report.findings:
            print(f"[{finding.level}] {finding.kind} :: {finding.path} :: {finding.message}")
        print(f"\nSummary: Errors={len(report.errors)} Warnings={len(report.warnings)}")

    if report.errors or (args.strict and report.warnings):
        return 1
    print('Public-readiness scan completed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
