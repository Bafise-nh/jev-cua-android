"""CLI: điều khiển app Android bằng Jev.

Ví dụ:
  python -m cua.run --doctor
  python -m cua.run --goal "Dang nhap quan demo" --package com.delitech.deli_merchant \
      --fill "Email=quan@test.vn" --fill "Mat khau=123456" --steps 15
  python -m cua.run --goal "..." --dry      # chỉ in state gửi Jev, không gọi API
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import partial

from . import agent, jev_client
from . import observe as obs


def _parse_fills(pairs: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise SystemExit(f"--fill phai co dang 'Nhan=gia tri': {item}")
        key, value = item.split("=", 1)
        result[key.strip()] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cua.run", description="Jev-driven Android UI agent")
    parser.add_argument("--goal", help="Mục tiêu bằng chữ, ví dụ: 'Mở Tổng quan và kiểm tra có checklist'")
    parser.add_argument("--package", help="Package app cần điều khiển, ví dụ com.delitech.deli_merchant")
    parser.add_argument("--fill", action="append", default=[], help="Dữ liệu điền: 'Nhãn=giá trị' (lặp lại được)")
    parser.add_argument("--expect", action="append", default=[], help="Chuỗi phải thấy trên màn hình để coi là xong (lặp lại được)")
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--no-fast", action="store_true", help="Tắt phát lại kế hoạch đã học")
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--trace-dir", default=str(agent.Path(__file__).parent.parent / "runs"))
    parser.add_argument("--shots", help="Thư mục lưu ảnh chụp từng bước")
    parser.add_argument("--doctor", action="store_true", help="Kiểm tra adb/thiết bị/màn hình")
    parser.add_argument("--backend", choices=["auto", "u2", "adb"], default="auto",
                        help="Cách lấy cây UI: u2 (nhanh, cần uiautomator2) / adb / auto")
    parser.add_argument("--dry", action="store_true", help="Chỉ quan sát + in state, không gọi Jev")
    args = parser.parse_args(argv)

    if args.doctor:
        devices = obs.devices()
        print(f"devices: {devices or 'KHONG CO'}")
        print(f"uiautomator2: {'co' if obs._u2 is not None else 'khong (dung adb, cham hon)'}")
        if not devices:
            return 1
        import time
        started = time.time()
        frame = obs.observe(backend=args.backend)
        elapsed = round((time.time() - started) * 1000)
        print(f"package: {frame.package or '?'}")
        print(f"size: {frame.width}x{frame.height}")
        print(f"elements: {len(frame.elements)} · {elapsed} ms")
        for el in frame.elements[:8]:
            print(f"  {el.id} {el.label[:40]!r} {el.role} {'editable' if el.editable else ''}")
        return 0

    if not args.goal:
        parser.error("can --goal (hoac --doctor)")

    if args.dry:
        frame = obs.observe(backend=args.backend)
        operations = agent.legal_operations(frame, _parse_fills(args.fill))
        state = frame.to_state(args.goal, [], operations)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        print("\n--- questions ---")
        print(json.dumps(agent.build_questions(frame, operations, _parse_fills(args.fill)), ensure_ascii=False, indent=2))
        return 0

    try:
        result = agent.run(
            args.goal,
            args.package,
            fills=_parse_fills(args.fill),
            expect=args.expect,
            fast=not args.no_fast,
            observer=partial(obs.observe, backend=args.backend),
            max_steps=args.steps,
            max_seconds=args.seconds,
            screenshot_dir=args.shots,
            trace_dir=args.trace_dir,
        )
    except RuntimeError as exc:
        print(f"LOI: {exc}")
        return 2

    print(f"ket qua: {'OK' if result.ok else 'DUNG'} — {result.reason}")
    print(f"so buoc: {result.steps} · {result.elapsed}s · trace: {result.trace_path}")
    if result.detail:
        print("chi tiet: " + json.dumps(result.detail, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
