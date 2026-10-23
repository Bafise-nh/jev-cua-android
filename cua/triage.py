"""Chạy test rồi nhờ Jev phân loại kết quả.

Ví dụ:
  python -m cua.triage --workdir C:\\...\\Deli-Merchant --command "flutter test"
  python -m cua.triage --workdir C:\\...\\Deli-Merchant-Api --command "php artisan test"
  python -m cua.triage --workdir ... --command "flutter test" --no-jev

Test xanh: in OK, thoát 0, không gọi Jev.
Test đỏ: gửi 150 dòng cuối log cho Jev, in action/blocking/evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import jev_client

QUESTIONS = {
    "action": {
        "type": "choice",
        "instructions": "What should the developer do next about this test run?",
        "criteria": {
            "pass": "All checks passed; nothing to fix.",
            "fix-code": "A real defect in the changed application code.",
            "fix-test": "The test itself is wrong, outdated, or asserts the wrong thing.",
            "flaky": "Passes and fails nondeterministically without a code change.",
            "env": "Environment, dependency, network, database, or CI setup problem.",
            "needs-human": "Evidence is insufficient or contradictory; a human must decide.",
        },
    },
    "blocking": {
        "type": "noul",
        "instructions": "This failure blocks merging or continuing work.",
    },
    "evidence": {
        "type": "score",
        "instructions": "How clear is the evidence for the chosen action?",
        "criteria": [
            "Little evidence, mostly guessing",
            "Some concrete signal in the logs",
            "Clear, specific evidence such as a stack trace pointing at the change",
        ],
    },
}

LOG_DIR = Path(__file__).parent.parent / "logs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cua.triage")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--tail", type=int, default=150)
    parser.add_argument("--no-jev", action="store_true")
    args = parser.parse_args(argv)

    workdir = Path(args.workdir)
    if not workdir.is_dir():
        print(f"Khong tim thay thu muc: {workdir}")
        return 2

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"test-{stamp}.log"

    print(f"=== chay: {args.command} (trong {workdir}) ===", flush=True)
    started = time.time()

    proc = subprocess.run(
        args.command,
        cwd=str(workdir),
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output = (proc.stdout or "") + (proc.stderr or "")
    log_path.write_text(output, encoding="utf-8")
    print(output[-4000:] if len(output) > 4000 else output)

    elapsed = round(time.time() - started, 1)
    print(f"\n=== exit {proc.returncode} · {elapsed}s · log: {log_path} ===")

    if proc.returncode == 0:
        print("Tat ca deu qua.")
        return 0

    if args.no_jev:
        return proc.returncode

    lines = output.splitlines()
    tail = "\n".join(lines[-args.tail:])
    state = (
        f"Command: {args.command}\n"
        f"Exit code: {proc.returncode}\n"
        f"Duration: {elapsed}s\n\n"
        f"--- tail of output ---\n{tail}"
    )

    print("\n=== Jev phan loai ===")
    try:
        response = jev_client.decide(state, QUESTIONS)
    except Exception as exc:  # noqa: BLE001
        print(f"Jev loi: {exc}")
        return proc.returncode

    answers = response.get("answers", {})
    action = answers.get("action", {})
    choice = action.get("choice")
    probs = action.get("probabilities") or {}
    ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:3]

    print(f"model: {response.get('model')} · tokens: "
          f"{(response.get('usage') or {}).get('input_tokens')} in / "
          f"{(response.get('usage') or {}).get('output_tokens')} out")
    print(f"  action: {choice} (conf {action.get('confidence', 0):.2f}; "
          + ", ".join(f"{k}={v:.2f}" for k, v in ranked) + ")")
    print(f"  blocking: {(answers.get('blocking') or {}).get('noul', 0):.2f}")
    evidence = answers.get("evidence") or {}
    print(f"  evidence: {evidence.get('score', 0):.2f}")

    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
