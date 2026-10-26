"""Chẩn đoán lỗi khi vận hành: đưa bằng chứng (lệnh + output) cho Jev chọn
nguyên nhân khả dĩ nhất và bước kiểm tra tiếp theo.

Dùng:
  python -m cua.diagnose --file loi.txt
  python -m cua.diagnose --text "command ... output ..."
"""

from __future__ import annotations

import argparse
import sys

from . import jev_client

QUESTIONS = {
    "cause": {
        "type": "choice",
        "instructions": "Which cause best explains this failure, given the evidence?",
        "criteria": {
            "auth-token": "The token is missing, not saved, disabled, or belongs to an inactive user.",
            "auth-guard": "The token is valid but the wrong auth guard/middleware consumes the request.",
            "config": "Configuration (env, cached config, database name, queue driver) points somewhere else.",
            "schema-data": "The database schema or data differs from what the code expects.",
            "network": "Connectivity, port, host-gateway, tunnel, DNS or firewall.",
            "code": "A logic bug in the changed application code.",
            "environment": "Runtime/tooling problem unrelated to application logic.",
        },
    },
    "next_step": {
        "type": "choice",
        "instructions": "What single check gives the most information for the least effort?",
        "criteria": {
            "inspect-schema": "Read the table columns / actual row values.",
            "inspect-code": "Read the middleware or handler that rejects the request.",
            "set-data": "Write the missing row/flag/token and retry once.",
            "switch-path": "Bypass the failing component with a known-good path to isolate it.",
            "read-logs": "Read the application log around the failure.",
            "restart": "Restart the process/container to rule out stale state.",
        },
    },
    "evidence": {
        "type": "score",
        "instructions": "How sufficient is the evidence to act on the chosen cause?",
        "criteria": [
            "Guesswork; the evidence does not distinguish causes",
            "Partial: one signal points at it but alternatives remain",
            "Strong: the failure and the cause are directly connected in the evidence",
        ],
    },
    "blocking": {
        "type": "noul",
        "instructions": "This failure blocks the end-to-end test.",
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cua.diagnose")
    parser.add_argument("--file")
    parser.add_argument("--text")
    args = parser.parse_args(argv)

    if args.file:
        state = open(args.file, encoding="utf-8").read()
    elif args.text:
        state = args.text
    else:
        parser.error("can --file hoac --text")

    response = jev_client.decide(state, QUESTIONS)
    answers = response.get("answers", {})
    cause = answers.get("cause", {})
    step = answers.get("next_step", {})

    print(f"model: {response.get('model')}")
    print(f"  cause: {cause.get('choice')} (conf {cause.get('confidence', 0):.2f})")
    ranked = sorted((cause.get("probabilities") or {}).items(), key=lambda kv: kv[1], reverse=True)[:3]
    print("    " + ", ".join(f"{k}={v:.2f}" for k, v in ranked))
    print(f"  next:  {step.get('choice')} (conf {step.get('confidence', 0):.2f})")
    print(f"  evidence: {(answers.get('evidence') or {}).get('score', 0):.2f}")
    print(f"  blocking: {(answers.get('blocking') or {}).get('noul', 0):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
