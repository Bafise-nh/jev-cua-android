"""Vòng lặp computer-use: quan sát → Jev chọn 1 hành động → guard → thực thi.

Nguyên tắc (theo blog fka.dev + CUA-JEV):
- Jev chỉ nhận state dạng chữ, không nhận ảnh/toạ độ.
- Mỗi bước chỉ làm MỘT hành động, rồi quan sát lại.
- Ngưỡng xác suất là cổng thật: hành động thường 0.55/0.35; hành động có hệ quả
  (gửi/đặt/huỷ/thanh toán) 0.85/0.75 + cho phép rõ ràng >= 0.90.
- DONE chỉ khi xác suất >= 0.90 VÀ câu "đã hoàn thành" >= 0.90.
- Trước khi bấm, quan sát lại frame mới và bám lại đúng phần tử; mất thì bỏ qua.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import jev_client
from . import observe as obs

MIN_PROB = 0.55
MIN_CONF = 0.35
STRONG_PROB = 0.85
STRONG_CONF = 0.75
AUTH_PROB = 0.90
DONE_PROB = 0.90
DONE_VERIFIED = 0.90
MAX_WAITS = 3
MAX_REPEATS = 3


@dataclass
class Result:
    ok: bool
    reason: str
    steps: int
    elapsed: float
    trace_path: str | None = None
    detail: dict = field(default_factory=dict)


class Executor:
    """Thực thi hành động thật qua adb."""

    def tap(self, el: obs.Element) -> None:
        self.tap_point(el.cx, el.cy)

    def tap_point(self, x: int, y: int) -> None:
        obs.adb("shell", "input", "tap", str(int(x)), str(int(y)))

    def type_text(self, value: str) -> None:
        safe = value.replace(" ", "%s").replace("&", "\\&")
        if any(ord(ch) > 127 for ch in value):
            raise RuntimeError("adb input text khong go duoc dau tieng Viet; dung ASCII")
        obs.adb("shell", "input", "text", safe)

    def back(self) -> None:
        obs.adb("shell", "input", "keyevent", "4")

    def scroll(self, direction: str, frame: obs.Frame, el: obs.Element | None = None) -> None:
        if el is not None:
            cx, cy = el.cx, el.cy
            span = max(80, min(400, (el.y2 - el.y1) // 2))
        else:
            cx, cy = frame.width // 2, frame.height // 2
            span = max(200, frame.height // 4)
        delta = span if direction == "down" else -span
        obs.adb(
            "shell", "input", "swipe",
            str(cx), str(cy + delta), str(cx), str(cy - delta), "300",
        )


# ---------------------------------------------------------------- questions


def _norm(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _cache_key(goal: str, frame: obs.Frame, operations: list[str]) -> str:
    """Khoá cache bền qua các lần chạy: bỏ số (giờ, tiền, đếm) để không đổi."""
    parts = [goal, ",".join(operations)]
    for el in frame.elements:
        label = re.sub(r"\d+", "#", el.label or "")
        parts.append(f"{label}|{el.role}|{int(el.clickable)}|{int(el.editable)}")
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()


def _visible(frame: obs.Frame, needle: str) -> bool:
    """Chuỗi cần thấy có xuất hiện trên màn hình không (bỏ dấu, không phân biệt hoa thường)."""
    target = _norm(needle)
    if not target:
        return True
    return any(target in _norm(text) for text in frame.screen_text)


def _plan_key(goal: str, expect: list[str]) -> str:
    return hashlib.sha1((goal + "|" + ",".join(expect)).encode("utf-8")).hexdigest()


def _load_plans(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _replay(
    plan,
    *,
    expect: list[str],
    observer,
    executor,
    package: str | None,
) -> obs.Frame | None:
    """Phát lại kế hoạch đã học.

    Nếu kế hoạch có toạ độ và đúng độ phân giải thiết bị: bấm thẳng theo toạ độ
    (chỉ 1 lần quan sát để kiểm tra cuối). Nếu không: quan sát trước rồi bấm theo
    nhãn. Trả None khi không bấm được hoặc sai kết quả (bên gọi quay về vòng đầy đủ).
    """
    entry = plan if isinstance(plan, dict) else {"actions": plan}
    actions = entry.get("actions") or []
    if not actions:
        return None

    blind = False
    stored_screen = entry.get("screen")
    if stored_screen and all("x" in a for a in actions if a.get("op") == "tap"):
        try:
            current = obs.adb("shell", "wm", "size").replace(" ", "")
            if stored_screen in current or stored_screen == "unknown":
                blind = True
        except Exception:  # noqa: BLE001
            blind = False

    frame = None
    if not blind:
        frame = observer(None)
        if package and frame.package and package not in frame.package:
            return None

    for action in actions:
        operation = action.get("op")

        if operation == "back":
            executor.back()
            time.sleep(0.35)
            continue

        if operation == "scroll":
            executor.scroll(action.get("direction") or "down", frame)
            time.sleep(0.35)
            continue

        if operation == "typeText":
            label = action.get("label") or ""
            field = next(
                (el for el in (frame.elements if frame else []) if el.label == label),
                None,
            )
            if field is None:
                return None
            executor.tap(field)
            time.sleep(0.4)
            executor.type_text(action.get("value") or "")
            time.sleep(0.35)
            continue

        # tap
        if blind and "x" in action:
            executor.tap_point(action["x"], action["y"])
        else:
            label = action.get("label") or ""
            role = action.get("role")
            target = next(
                (el for el in frame.elements if el.label == label and el.role == role),
                None,
            ) or next((el for el in frame.elements if el.label == label), None)
            if target is None:
                return None
            executor.tap(target)
        time.sleep(0.35)

    end = observer(None)
    if all(_visible(end, item) for item in expect):
        return end
    return None


def fill_target(frame: obs.Frame, fills: dict[str, str]) -> tuple[obs.Element, str] | None:
    """Trường đang focus + giá trị cần gõ (khớp theo nhãn)."""
    el = frame.focused_editable
    if el is None or el.password:
        return None
    label = _norm(el.label)
    if not label:
        return None
    for key, value in fills.items():
        k = _norm(key)
        if k and (k in label or label in k):
            return el, value
    return None


def legal_operations(frame: obs.Frame, fills: dict[str, str]) -> list[str]:
    ops = ["tap", "scroll", "back", "WAIT", "DONE", "BLOCKED"]
    if fill_target(frame, fills) is not None:
        ops.append("typeText")
    return ops


def build_questions(frame: obs.Frame, operations: list[str], fills: dict[str, str]) -> dict:
    targets = {
        el.id: f"{el.label or '(khong nhan)'} · {el.role} · {el.coarse_position(frame.width, frame.height)}"
        for el in frame.elements
    }
    targets["none"] = "Không có phần tử nào khớp."

    criteria = {
        "tap": "Bấm vào một phần tử đang hiện trên màn hình.",
        "scroll": "Vuốt danh sách, không bấm.",
        "back": "Bấm nút Back của Android.",
        "WAIT": "Quan sát lại, chưa làm gì (màn hình đang tải/chuyển cảnh).",
        "DONE": "Màn hình hiện tại chứng minh mục tiêu đã hoàn thành đầy đủ.",
        "BLOCKED": "Không có hành động hợp lệ nào tiến được mục tiêu một cách an toàn.",
    }
    if "typeText" in operations:
        criteria["typeText"] = "Gõ giá trị đã cho vào trường đang focus. Không bấm gửi."

    questions: dict = {
        "nextOperation": {
            "type": "choice",
            "instructions": "Chọn đúng MỘT hành động kế tiếp có thể thực thi.",
            "criteria": {op: criteria[op] for op in operations},
        },
        "tapTarget": {
            "type": "choice",
            "instructions": "Nếu chọn tap, chọn đúng phần tử cần bấm.",
            "criteria": targets,
        },
        "scrollDirection": {
            "type": "choice",
            "instructions": "Nếu chọn scroll, chọn hướng vuốt.",
            "criteria": {
                "down": "Xem nội dung phía dưới.",
                "up": "Xem nội dung phía trên.",
                "none": "Không cần vuốt.",
            },
        },
        "completionVerified": {
            "type": "noul",
            "instructions": "Màn hình hiện tại có chứng minh mục tiêu đã hoàn thành đầy đủ chưa?",
        },
        "consequential": {
            "type": "noul",
            "instructions": "Hành động kế tiếp có gửi/đặt hàng/huỷ/thanh toán/xoá hoặc gây hệ quả thật không?",
        },
        "explicitAuthorization": {
            "type": "noul",
            "instructions": "Mục tiêu có cho phép rõ ràng hệ quả đó ngay bây giờ không?",
        },
    }
    return questions


# ---------------------------------------------------------------- guards


def _answer(answers: dict, key: str) -> dict:
    value = answers.get(key)
    return value if isinstance(value, dict) else {}


def gate(answers: dict, operation: str) -> tuple[bool, str]:
    """Kiểm tra ngưỡng cho hành động đã chọn."""
    op_answer = _answer(answers, "nextOperation")
    prob = float((op_answer.get("probabilities") or {}).get(operation, 0.0))
    conf = float(op_answer.get("confidence") or 0.0)

    if operation == "DONE":
        verified = float(_answer(answers, "completionVerified").get("noul") or 0.0)
        if prob < DONE_PROB:
            return False, f"DONE prob {prob:.2f} < {DONE_PROB}"
        if verified < DONE_VERIFIED:
            return False, f"completionVerified {verified:.2f} < {DONE_VERIFIED}"
        return True, "done"

    if operation in ("BLOCKED", "WAIT"):
        return True, operation.lower()

    consequential = float(_answer(answers, "consequential").get("noul") or 0.0)
    authorized = float(_answer(answers, "explicitAuthorization").get("noul") or 0.0)

    if consequential >= 0.5:
        if prob < STRONG_PROB or conf < STRONG_CONF:
            return False, (
                f"hành động có hệ quả nhưng prob {prob:.2f}/conf {conf:.2f} "
                f"< {STRONG_PROB}/{STRONG_CONF}"
            )
        if authorized < AUTH_PROB:
            return False, f"chưa được cho phép rõ ràng ({authorized:.2f} < {AUTH_PROB})"
        return True, "strong"

    if prob < MIN_PROB or conf < MIN_CONF:
        return False, f"prob {prob:.2f}/conf {conf:.2f} < {MIN_PROB}/{MIN_CONF}"
    return True, "normal"


def _choose(answers: dict, question: str) -> tuple[str | None, float, float]:
    answer = _answer(answers, question)
    choice = answer.get("choice")
    prob = float((answer.get("probabilities") or {}).get(choice, 0.0)) if choice else 0.0
    return choice, prob, float(answer.get("confidence") or 0.0)


# ---------------------------------------------------------------- rebind


def rebind(frame: obs.Frame, label: str, role: str, cx: int, cy: int) -> obs.Element | None:
    """Tìm lại phần tử trong frame mới theo nhãn + vai trò + khoảng cách gần nhất."""
    candidates = [el for el in frame.elements if el.label == label and el.role == role]
    if not candidates:
        candidates = [el for el in frame.elements if el.label == label]
    if not candidates:
        return None
    return min(candidates, key=lambda el: (el.cx - cx) ** 2 + (el.cy - cy) ** 2)


# ---------------------------------------------------------------- loop


def run(
    goal: str,
    package: str | None = None,
    *,
    fills: dict[str, str] | None = None,
    expect: list[str] | None = None,
    decide=jev_client.decide,
    observer=obs.observe,
    executor=None,
    max_steps: int = 25,
    max_seconds: int = 180,
    screenshot_dir: str | None = None,
    trace_dir: str = str(Path(__file__).parent.parent / "runs"),
    use_cache: bool = True,
    fast: bool = True,
) -> Result:
    executor = executor or Executor()
    fills = fills or {}
    expect = [item for item in (expect or []) if item]
    started = time.time()
    recent: list[str] = []
    trace: list[dict] = []
    waits = 0
    last_key = None
    repeats = 0

    Path(trace_dir).mkdir(parents=True, exist_ok=True)
    trace_path = Path(trace_dir) / f"run-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    cache_path = Path(trace_dir) / "decisions.json"
    plan_path = Path(trace_dir) / "plans.json" if expect else None
    plan_key = _plan_key(goal, expect) if expect else ""
    plans = _load_plans(plan_path) if plan_path is not None else {}
    replayable_actions: list[dict] = []
    screen_label = "unknown"
    cache: dict = {}
    if use_cache and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}

    def finish(ok: bool, reason: str, step: int, **detail) -> Result:
        with trace_path.open("w", encoding="utf-8") as handle:
            for row in trace:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if use_cache:
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False), encoding="utf-8"
            )
        if (
            ok
            and expect
            and plan_path is not None
            and replayable_actions
            and reason in ("expect-satisfied", "done")
        ):
            plans[plan_key] = {
                "screen": screen_label,
                "actions": replayable_actions,
            }
            plan_path.write_text(
                json.dumps(plans, ensure_ascii=False), encoding="utf-8"
            )
        return Result(
            ok=ok,
            reason=reason,
            steps=step,
            elapsed=round(time.time() - started, 1),
            trace_path=str(trace_path),
            detail=detail,
        )

    if fast and plan_path is not None and plan_key in plans:
        replayed = _replay(
            plans[plan_key],
            expect=expect,
            observer=observer,
            executor=executor,
            package=package,
        )
        if replayed is not None:
            trace.append({"step": 0, "mode": "replay", "plan": plans[plan_key]})
            return finish(True, "replay-satisfied", 0)

    for step in range(1, max_steps + 1):
        if time.time() - started > max_seconds:
            return finish(False, "timeout", step)
        t_obs = time.time()
        frame = observer(
            str(Path(screenshot_dir) / f"step-{step:02d}.png")
            if screenshot_dir
            else None
        )
        obs_ms = round((time.time() - t_obs) * 1000)
        if screen_label == "unknown":
            screen_label = f"{frame.width}x{frame.height}"

        # Kiểm tra kết quả bằng văn bản hiện trên màn hình — không phụ thuộc
        # vào việc model tự nói "xong". Đây là điều kiện của TEST.
        if expect and step > 1 and all(_visible(frame, item) for item in expect):
            return finish(True, "expect-satisfied", step)

        if package and frame.package and package not in frame.package:
            return finish(
                False,
                "foreground-mismatch",
                step,
                expected=package,
                actual=frame.package,
            )

        operations = legal_operations(frame, fills)
        state = frame.to_state(goal, recent, operations)
        questions = build_questions(frame, operations, fills)

        try:
            t_decide = time.time()
            state_key = _cache_key(goal, frame, operations)
            if use_cache and state_key in cache:
                response = {"answers": cache[state_key], "cached": True}
                cached = True
            else:
                response = decide(state, questions)
                cache[state_key] = response.get("answers", {})
                cached = False
            decide_ms = round((time.time() - t_decide) * 1000)
        except Exception as exc:  # noqa: BLE001 - lỗi mạng/API -> dừng an toàn
            return finish(False, f"jev-error: {exc}", step)

        answers = response.get("answers", {})
        operation = (_answer(answers, "nextOperation").get("choice") or "")

        if operation not in operations:
            return finish(False, f"invalid-operation: {operation!r}", step)

        allowed, why = gate(answers, operation)
        row = {
            "step": step,
            "obs_ms": obs_ms,
            "decide_ms": decide_ms,
            "cached": cached,
            "screen": hashlib.sha1(
                ("|".join(frame.screen_text)).encode("utf-8")
            ).hexdigest()[:12],
            "operation": operation,
            "gate": why,
            "allowed": allowed,
            "next_probs": _answer(answers, "nextOperation").get("probabilities"),
            "completion": _answer(answers, "completionVerified").get("noul"),
        }

        if operation == "DONE":
            trace.append(row)
            missing = [item for item in expect if not _visible(frame, item)]
            if missing:
                # Model nói xong nhưng bằng chứng trên màn hình chưa có.
                why = "thiếu: " + ", ".join(missing)
                recent.append(f"Chưa hoàn thành — {why}")
                trace[-1]["blocked"] = why
                waits += 1
                if waits > MAX_WAITS:
                    return finish(False, f"stuck: {why}", step)
                continue
            if allowed:
                return finish(True, "done", step)
            recent.append(f"Bị chặn DONE: {why}")
            trace[-1]["blocked"] = why
            waits += 1
            if waits > MAX_WAITS:
                return finish(False, f"stuck: {why}", step)
            continue

        if operation == "BLOCKED":
            trace.append(row)
            return finish(False, f"blocked-by-model: {why}", step)

        if operation == "WAIT" or not allowed:
            trace.append(row)
            if not allowed:
                recent.append(f"Bị chặn {operation}: {why}")
            waits += 1
            if waits > MAX_WAITS:
                return finish(False, f"stuck: {why}" if not allowed else "stuck-waiting", step)
            time.sleep(1.0)
            continue

        # --- tìm mục tiêu trong frame hiện tại ---
        target: obs.Element | None = None
        value: str | None = None

        if operation == "tap":
            target_id, target_prob, _ = _choose(answers, "tapTarget")
            row["target"] = target_id
            row["target_prob"] = round(target_prob, 2)
            target = next((el for el in frame.elements if el.id == target_id), None)
            if target is None or target_prob < MIN_PROB:
                trace.append(row)
                recent.append(f"Bị chặn tap: mục tiêu {target_id} không rõ")
                waits += 1
                if waits > MAX_WAITS:
                    return finish(False, "target-ambiguous", step)
                continue
            if target.password:
                trace.append(row)
                return finish(False, "password-field", step, label=target.label)

        elif operation == "typeText":
            found = fill_target(frame, fills)
            if found is None:
                trace.append(row)
                return finish(False, "no-fill-target", step)
            target, value = found

        elif operation == "scroll":
            direction, direction_prob, _ = _choose(answers, "scrollDirection")
            if direction not in ("up", "down") or direction_prob < MIN_PROB:
                trace.append(row)
                recent.append("Bị chặn scroll: hướng không rõ")
                continue
            row["direction"] = direction

        # --- frame mới: bám lại mục tiêu trước khi thực thi ---
        if target is not None:
            t_fresh = time.time()
            fresh = observer(None)
            row["fresh_ms"] = round((time.time() - t_fresh) * 1000)
            bound = rebind(fresh, target.label, target.role, target.cx, target.cy)
            if bound is None:
                trace.append({**row, "stale": True})
                recent.append("Mục tiêu đã biến mất, quan sát lại")
                waits += 1
                if waits > MAX_WAITS:
                    return finish(False, "target-lost", step)
                continue
            target = bound

        # --- chống lặp ---
        key = (operation, target.label if target else row.get("direction"))
        if key == last_key:
            repeats += 1
            if repeats >= MAX_REPEATS:
                trace.append({**row, "loop": True})
                return finish(False, "loop-detected", step, action=str(key))
        else:
            repeats = 0
            last_key = key

        # --- thực thi ---
        try:
            if operation == "tap":
                executor.tap(target)
                recent.append(f"Đã bấm: {target.label or target.role}")
                replayable_actions.append(
                    {
                        "op": "tap",
                        "label": target.label,
                        "role": target.role,
                        "x": target.cx,
                        "y": target.cy,
                    }
                )
            elif operation == "typeText":
                executor.type_text(value or "")
                recent.append(f"Đã gõ vào: {target.label}")
                replayable_actions.append(
                    {
                        "op": "typeText",
                        "label": target.label,
                        "role": target.role,
                        "value": value,
                    }
                )
            elif operation == "scroll":
                scroll_el = next(
                    (el for el in frame.elements if el.scrollable), None
                )
                executor.scroll(row.get("direction", "down"), frame, scroll_el)
                recent.append(f"Đã vuốt: {row.get('direction')}")
                replayable_actions.append(
                    {"op": "scroll", "direction": row.get("direction")}
                )
            elif operation == "back":
                executor.back()
                recent.append("Đã bấm Back")
                replayable_actions.append({"op": "back"})
        except Exception as exc:  # noqa: BLE001
            trace.append({**row, "error": str(exc)})
            return finish(False, f"exec-error: {exc}", step)

        waits = 0
        trace.append({**row, "executed": True})
        time.sleep(0.6)

    return finish(False, "max-steps", max_steps)
