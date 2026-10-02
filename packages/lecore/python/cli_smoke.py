#!/usr/bin/env python3
"""Reproduce the paired, actual OpenCode CLI coding smoke on public fixtures.

Run from any directory with this package's Python. --prepare-only writes the
identical fixtures without calling a model. A live run allows six agent turns
per arm; CLI-generated titles may make one additional small-model call per arm.
Results retain raw JSON events, CLI logs, edited sources, and independent grades.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


IMPLEMENTATION = '''import time

def retry(call, attempts=3, delay=0.0, sleep=time.sleep):
    """Retry an operation on transient OSError failures."""
    return call()
'''

TESTS = '''import unittest
from retry import retry

class RetryTests(unittest.TestCase):
    def test_retries_and_backs_off(self):
        count=[0]; waits=[]
        def task():
            count[0]+=1
            if count[0]<3: raise OSError("transient")
            return "done"
        self.assertEqual(retry(task, attempts=4, delay=0.25, sleep=waits.append), "done")
        self.assertEqual(count[0],3)
        self.assertEqual(waits,[0.25,0.5])
    def test_final_error_is_same_instance_no_final_sleep(self):
        error=OSError("still down"); waits=[]; count=[0]
        def task():
            count[0]+=1; raise error
        with self.assertRaises(OSError) as got: retry(task, attempts=3, delay=2, sleep=waits.append)
        self.assertIs(got.exception,error); self.assertEqual(count[0],3); self.assertEqual(waits,[2,4])
    def test_non_transient_error_is_not_retried(self):
        error=ValueError("bad argument"); count=[0]; waits=[]
        def task():
            count[0]+=1; raise error
        with self.assertRaises(ValueError) as got: retry(task, attempts=5, sleep=waits.append)
        self.assertIs(got.exception,error); self.assertEqual(count[0],1); self.assertEqual(waits,[])
    def test_zero_delay_can_use_zero_backoff(self):
        attempts=[False,True]; waits=[]
        def task():
            if not attempts.pop(0): raise OSError()
            return 42
        self.assertEqual(retry(task, delay=0, sleep=waits.append),42)
        self.assertTrue(all(x==0 for x in waits))
    def test_attempts_positive(self):
        for n in (0,-1):
            with self.assertRaises(ValueError): retry(lambda:None, attempts=n)
    def test_no_sleep_after_immediate_success(self):
        waits=[]; self.assertEqual(retry(lambda:None,sleep=waits.append),None); self.assertEqual(waits,[])

if __name__=="__main__": unittest.main()
'''

PROMPT = (
    "Fix retry.py to satisfy test_retry.py. Retry only OSError subclasses at most attempts total calls, "
    "reject attempts below 1 before calling, sleep with exponential delay between failures but never after "
    "final failure, re-raise the exact last exception, and return successes unchanged. Run python3 -m unittest "
    "-v to verify. Edit only retry.py; do not change the tests or install dependencies. All work stays in this "
    "generated public fixture directory. Then report test results briefly."
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="opencode/glm-5.3-flash")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--fixed-title", action="store_true", help="suppress automatic small-model title generation")
    args = parser.parse_args()
    root = (args.output or Path(tempfile.mkdtemp(prefix="opencode-lecore-cli-smoke-"))).resolve()
    if (root / "results.json").exists():
        parser.error("output already contains results; choose a new directory")
    root.mkdir(parents=True, exist_ok=True)
    (root / "prompt.txt").write_text(PROMPT)
    config = {"permission": {"external_directory": "deny", "webfetch": "deny", "bash": "allow", "edit": "allow",
                             "read": "allow", "glob": "allow", "grep": "allow"}, "agent": {"build": {"steps": 6}}}
    for arm in ("baseline", "lecore"):
        directory = root / arm
        directory.mkdir(exist_ok=True)
        (directory / "retry.py").write_text(IMPLEMENTATION)
        (directory / "test_retry.py").write_text(TESTS)
        (directory / "opencode.json").write_text(json.dumps(config))
    if args.prepare_only:
        print(root)
        return
    repo = Path(__file__).resolve().parents[3]
    results = []
    for arm in ("baseline", "lecore"):
        directory = root / arm
        env = dict(os.environ, OPENCODE_LECORE="0" if arm == "baseline" else "1",
                   LECORE_STORAGE_DIR=str(directory / ".lecore-state"), PYTHONDONTWRITEBYTECODE="1")
        command = [str(repo / "script" / "lecore.sh"), "run", "--pure", "--auto", "--format", "json",
                   "--print-logs", "--log-level", "INFO", "--model", args.model]
        if args.fixed_title:
            command.extend(["--title", "leCore CLI smoke"])
        command.append(PROMPT)
        started = time.monotonic()
        with (root / f"{arm}.events.jsonl").open("w") as out, (root / f"{arm}.stderr.txt").open("w") as err:
            child = subprocess.Popen(command, cwd=directory, env=env, stdout=out, stderr=err, start_new_session=True)
            timed_out = False
            try:
                code = child.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "posix":
                    os.killpg(child.pid, signal.SIGTERM)
                else:
                    child.terminate()
                try:
                    code = child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(child.pid, signal.SIGKILL)
                    else:
                        child.kill()
                    code = child.wait()
        grade = subprocess.run([sys.executable, "-m", "unittest", "-v"], cwd=directory, capture_output=True, text=True)
        (root / f"{arm}.grade.txt").write_text(grade.stdout + grade.stderr)
        events = []
        for line in (root / f"{arm}.events.jsonl").read_text().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        usage = [event["part"] for event in events if event.get("type") == "step_finish"]
        tests_unchanged = hashlib.sha256((directory / "test_retry.py").read_bytes()).hexdigest() == hashlib.sha256(TESTS.encode()).hexdigest()
        row = {"arm": arm, "model": args.model, "exit_code": code, "timed_out": timed_out,
               "elapsed_seconds": round(time.monotonic() - started, 2), "tests_passed": grade.returncode == 0 and tests_unchanged,
               "tests_unchanged": tests_unchanged, "step_finishes": len(usage), "usage": usage,
               "cost_usd": round(sum(part["cost"] for part in usage), 8),
               "prompt_tokens": sum(part["tokens"]["input"] + part["tokens"]["cache"]["read"] for part in usage),
               "cached_tokens": sum(part["tokens"]["cache"]["read"] for part in usage),
               "output_tokens": sum(part["tokens"]["output"] for part in usage),
               "tools": [event["part"]["tool"] for event in events if event.get("type") == "tool_use"],
               "fixture_path": str(directory), "events": str(root / f"{arm}.events.jsonl"), "stderr": str(root / f"{arm}.stderr.txt"),
               "automatic_title": not args.fixed_title,
               "cost_scope": "agent step events only; automatic title usage is not included"}
        results.append(row)
        (root / "results.json").write_text(json.dumps(results, indent=2))
        print(json.dumps({key: value for key, value in row.items() if key != "usage"}), flush=True)
    if not all(row["exit_code"] == 0 and row["tests_passed"] for row in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
