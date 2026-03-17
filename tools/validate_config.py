#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from powerbot_core.config_validation import validate_config_file


def main() -> int:
    parser = argparse.ArgumentParser(description='Validate PowerBot config.json structure.')
    parser.add_argument('config_path', nargs='?', default=Path('data') / 'config.json', type=Path)
    parser.add_argument('--json', action='store_true', dest='as_json')
    args = parser.parse_args()

    report = validate_config_file(args.config_path)
    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for issue in report.errors + report.warnings:
            print(f"[{issue.level}] {issue.key}: {issue.message}")
        print(f"\nSummary: Errors={len(report.errors)} Warnings={len(report.warnings)}")

    if report.errors:
        print('Config validation failed.')
        return 1
    print('Config validation passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
