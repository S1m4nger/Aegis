#!/usr/bin/env python3
"""Offline, non-destructive checks; does not submit anything."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
issues=[]
for f in ['README.md','docs/running.md','docs/architecture.md','docs/credits.md']:
    if not (root/f).exists(): issues.append(f'Missing {f}')
for f in ['CONTRIBUTING.md','CONTRIBUTORS.md']:
    if (root/f).exists(): issues.append(f'Unexpected contributor file {f}')
for pat in ('*_test.go','test_*.py','*_test.py'):
    stale=[p.relative_to(root).as_posix() for p in root.rglob(pat) if '.venv' not in p.parts and 'graphify-out' not in p.parts]
    if stale: issues.append(f'Temporary test sources remain ({pat}): {stale}')
r=(root/'README.md').read_text(encoding='utf8')
if 'This project is a prototype and is not financial advice.' not in r: issues.append('Missing finance disclaimer')
print('\n'.join(issues) if issues else 'Static checks OK. Submission/experiment NOT verified by this check.')
sys.exit(1 if issues else 0)
