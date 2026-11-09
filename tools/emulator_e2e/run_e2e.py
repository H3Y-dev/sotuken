"""CLI entrypoint for Emulator E2E test."""
from __future__ import annotations

import argparse
import sys
import os

# Ensure repo root is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.emulator_e2e.e2e_runner import E2ETestRunner


def main():
    parser = argparse.ArgumentParser(description="Run Android Emulator E2E test for meter inspection flow")
    parser.add_argument("--port", type=int, default=18765, help="Port for isolated PC receiver (default: 18765)")
    parser.add_argument("--keep-emulator", action="store_true", help="Keep emulator running after test completion")
    args = parser.parse_args()

    print("==================================================")
    print("  Starting Android Emulator Inspection E2E Test  ")
    print("==================================================")
    runner = E2ETestRunner(port=args.port, keep_emulator=args.keep_emulator)
    success = runner.run_all()

    print("\n==================================================")
    print(f"  E2E Test Result: {'SUCCESS' if success else 'FAILURE'}")
    print("==================================================")
    for res in runner.steps_results:
        status = "OK" if res.get("ok") else "NG"
        print(f"  [{status}] {res.get('step')}: {res.get('detail')}")

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
