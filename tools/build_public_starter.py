#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from powerbot_core.public_release import build_public_starter


def main() -> int:
    parser = argparse.ArgumentParser(description='Build a sanitized PowerBot public starter pack.')
    parser.add_argument('--project-root', default=PROJECT_ROOT, type=Path)
    parser.add_argument('--output-dir', default=PROJECT_ROOT / 'exports', type=Path)
    parser.add_argument('--starter-name', default='PowerBot-Core-Starter')
    args = parser.parse_args()

    summary = build_public_starter(args.project_root, args.output_dir, starter_name=args.starter_name)
    print(json.dumps(summary.to_dict(), indent=2))
    print(f"\n✅ Built starter pack at: {summary.output_root}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
