"""Client gọi Jev (/v1/systemone) — chỉ dùng stdlib.

Key: biến môi trường EXPERIENTIAL_API_KEY, nếu không có thì đọc auth.json của
opencode (provider `experientiallabs`). Không log key.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = os.environ.get(
    "JEV_ENDPOINT", "https://api.experientiallabs.ai/v1/systemone"
)
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
AUTH_PATH = Path(
    os.environ.get(
        "JEV_AUTH_FILE",
        str(Path.home() / ".local" / "share" / "opencode" / "auth.json"),
    )
)


def api_key() -> str:
    key = os.environ.get("EXPERIENTIAL_API_KEY")
    if key:
        return key
    if not AUTH_PATH.exists():
        raise RuntimeError(
            "Thieu EXPERIENTIAL_API_KEY va khong thay auth.json"
        )
    data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    key = (data.get("experientiallabs") or {}).get("key")
    if not key:
        raise RuntimeError("Khong tim thay key experientiallabs trong auth.json")
    return key


def decide(state, questions, timeout: int = 40) -> dict:
    """Gửi 1 request, trả nguyên JSON response. Không retry (tránh tính phí 2 lần)."""
    payload = {
        "model": MODEL,
        "state": state,
        "questions": questions,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise RuntimeError(f"Jev HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Jev khong ket noi duoc: {exc.reason}") from exc
