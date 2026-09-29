"""Rebuild the reading pilot, refresh the next queue and run all checks."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STEPS = [
    'build_pilot.py',
    'bulk_extract.py',
    'deep_read.py',
    'apply_context_reading.py',
    'apply_stateful_reading.py',
    'prepare_review_queue.py',
    'verify.py',
    'verify_pilot.py',
    'verify_stateful_reading.py',
    'verify_review_queue.py',
    'verify_site.py',
    'quality_report.py',
]

for script in STEPS:
    print(f'\n== {script} ==', flush=True)
    subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, check=True)

print('\nPilot refresh complete.')
