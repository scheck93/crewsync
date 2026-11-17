#!/usr/bin/env python3
"""Run crewsync.py for every client under clients/*/config.json.

Usage:
    python3 run_all.py            # real run for all clients
    python3 run_all.py --dry-run  # dry-run all clients
    python3 run_all.py --init-snapshot  # save current state, send nothing
"""
import os
import sys
import glob
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
flags = [a for a in sys.argv[1:] if a in ("--dry-run", "--init-snapshot")]
configs = sorted(glob.glob(os.path.join(HERE, "clients", "*", "config.json")))

if not configs:
    print("No clients found under clients/*/config.json", file=sys.stderr)
    sys.exit(1)

overall_rc = 0
for cfg in configs:
    name = os.path.basename(os.path.dirname(cfg))
    print(f"\n===== {name} =====")
    cmd = [sys.executable, os.path.join(HERE, "crewsync.py"), cfg]
    cmd += flags
    rc = subprocess.run(cmd).returncode
    overall_rc = overall_rc or rc

sys.exit(overall_rc)
