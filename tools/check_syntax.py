from __future__ import annotations

import py_compile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    checked = 0
    for py_file in root.rglob('*.py'):
        if '__pycache__' in py_file.parts:
            continue
        checked += 1
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{py_file.relative_to(root)}: {exc.msg}")
    if failures:
        print('PowerBot syntax check failed:\n')
        print('\n'.join(failures))
        return 1
    print(f'PowerBot syntax check passed ({checked} Python files).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
