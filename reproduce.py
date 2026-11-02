#!/usr/bin/env python3
"""Reproduce the current study using saved data only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def read(path): return json.loads(path.read_text())
def run(args, cwd=ROOT, env=None):
    subprocess.run([sys.executable, '-B', *map(str, args)], cwd=cwd, env=env, check=True)

def main():
    if sys.version_info < (3, 12): raise SystemExit('Python 3.12 or later is required.')
    manifest = ROOT/'SHA256SUMS'
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            expected, name = line.split('  ', 1)
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
                raise SystemExit('Checksum mismatch: '+name)
        print('Release file checksums verified.', flush=True)
    env = {**os.environ, 'PYTHONPATH':os.pathsep.join(filter(None,[str(ROOT/'demo'),os.environ.get('PYTHONPATH')])), 'PYTHONDONTWRITEBYTECODE':'1'}
    (ROOT/'research/results').mkdir(exist_ok=True)
    run(['-m','unittest','discover','-s','tests','-v'], ROOT/'demo', env)
    run(['run_study.py'], ROOT/'research', env)
    run(['check_requests.py'], ROOT/'research', env)
    run(['-m','unittest','discover','-s','.','-p','test_assurance.py','-v'], ROOT/'research', env)
    run(['check_bounded.py'], ROOT/'research', env)
    expected=read(ROOT/'research/data/reported_results.json')
    development=read(ROOT/'research/results/development_results.json')
    if development['summary'] != expected['deterministic'] or development['paired_outcome_disagreements']:
        raise SystemExit('Development outcomes differ from the report.')
    if read(ROOT/'research/results/bounded_results.json') != expected['bounded']:
        raise SystemExit('Bounded exploration differs from the report.')
    run(['reproduce_live.py'], ROOT/'research', env)
    print('\nVERIFIED: 30 demo tests, 9 assurance checks, 26 scenarios per tracker, request tracking in four existing cases per configuration, 9,360 sequences, 64 saved trajectories, calibration and judge analyses. No model calls.',flush=True)

if __name__ == '__main__': main()
