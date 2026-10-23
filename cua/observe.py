"""Quan sát màn hình Android bằng adb + uiautomator.

Trả về Frame: danh sách phần tử có id tạm (e1..eN), nhãn, vai trò, vị trí thô,
cờ enabled/focused/editable, kèm toạ độ thật (chỉ dùng nội bộ, không gửi Jev).
"""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass
class Element:
    id: str
    label: str
    role: str
    x1: int
    y1: int
    x2: int
    y2: int
    enabled: bool = True
    focused: bool = False
    editable: bool = False
    clickable: bool = False
    scrollable: bool = False
    password: bool = False

    @property
    def cx(self) -> int:
        return (self.x1 + self.x2) // 2

    @property
    def cy(self) -> int:
        return (self.y1 + self.y2) // 2

    def coarse_position(self, width: int, height: int) -> str:
        col = "left" if self.cx < width / 3 else ("right" if self.cx > 2 * width / 3 else "center")
        row = "top" if self.cy < height / 3 else ("bottom" if self.cy > 2 * height / 3 else "middle")
        return f"{row} {col}"

    def public(self, width: int, height: int) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "role": self.role,
            "enabled": self.enabled,
            "focused": self.focused,
            "editable": self.editable,
            "position": self.coarse_position(width, height),
        }


@dataclass
class Frame:
    package: str
    width: int
    height: int
    elements: list[Element] = field(default_factory=list)
    screen_text: list[str] = field(default_factory=list)
    secure_input: bool = False
    screenshot: str | None = None

    @property
    def focused_editable(self) -> Element | None:
        for el in self.elements:
            if el.editable and el.focused:
                return el
        return None

    def to_state(self, goal: str, recent: list[str], operations: list[str]) -> dict:
        return {
            "goal": goal,
            "screen": {
                "application": self.package,
                "screenText": self.screen_text[:40],
                "elements": [el.public(self.width, self.height) for el in self.elements[:40]],
                "secureInput": self.secure_input,
            },
            "capabilities": {"operations": operations},
            "recentActions": recent[-8:],
        }

    def to_json(self) -> dict:
        return {
            "package": self.package,
            "width": self.width,
            "height": self.height,
            "secureInput": self.secure_input,
            "screenshot": self.screenshot,
            "elements": [
                {
                    "id": el.id,
                    "label": el.label,
                    "role": el.role,
                    "bounds": [el.x1, el.y1, el.x2, el.y2],
                    "enabled": el.enabled,
                    "focused": el.focused,
                    "editable": el.editable,
                    "clickable": el.clickable,
                    "scrollable": el.scrollable,
                    "password": el.password,
                }
                for el in self.elements
            ],
        }


def adb(*args: str, timeout: int = 20) -> str:
    proc = subprocess.run(
        ["adb", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)} loi: {proc.stderr.strip()}")
    return proc.stdout


def devices() -> list[str]:
    out = adb("devices")
    result = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            result.append(parts[0])
    return result


def screen_size() -> tuple[int, int]:
    out = adb("shell", "wm", "size")
    match = re.search(r"(\d+)x(\d+)", out)
    if not match:
        return 1080, 2400
    return int(match.group(1)), int(match.group(2))


def current_package() -> str:
    out = adb("shell", "dumpsys", "window")
    for pattern in (r"mCurrentFocus=Window\{[^ ]+ [^ ]+ ([^/\s]+)", r"mFocusedApp=.*? ([^/\s]+)/"):
        match = re.search(pattern, out)
        if match:
            return match.group(1)
    return ""


def _role(node: ET.Element) -> str:
    cls = (node.get("class") or "").lower()
    if "edittext" in cls:
        return "text field"
    if "button" in cls:
        return "button"
    if "switch" in cls or "checkbox" in cls:
        return "switch"
    if "image" in cls:
        return "image"
    if node.get("clickable") == "true":
        return "clickable"
    if node.get("scrollable") == "true":
        return "scrollable"
    return "text"


def observe(screenshot_path: str | None = None) -> Frame:
    """Chụp trạng thái UI hiện tại. Ném RuntimeError nếu không có thiết bị."""
    if not devices():
        raise RuntimeError("Khong co thiet bi/emulator nao (adb devices rong).")

    width, height = screen_size()
    package = current_package()

    adb("shell", "uiautomator", "dump", "/sdcard/jev-ui.xml")
    xml_text = adb("exec-out", "cat", "/sdcard/jev-ui.xml")

    frame = Frame(package=package, width=width, height=height)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"Khong parse duoc UI dump: {exc}") from exc

    seen: set[tuple] = set()
    texts: list[str] = []

    for node in root.iter("node"):
        match = BOUNDS_RE.search(node.get("bounds") or "")
        if not match:
            continue
        x1, y1, x2, y2 = (int(v) for v in match.groups())
        if x2 <= x1 or y2 <= y1:
            continue

        label = (node.get("text") or "").strip() or (node.get("content-desc") or "").strip()
        clickable = node.get("clickable") == "true"
        scrollable = node.get("scrollable") == "true"
        editable = "edittext" in (node.get("class") or "").lower()
        password = node.get("password") == "true"
        focused = node.get("focused") == "true"
        enabled = node.get("enabled") != "false"

        if label and len(label) <= 120 and label not in texts:
            texts.append(label)

        # Chỉ đưa vào danh sách hành động những gì bấm/gõ/scroll được hoặc có nhãn.
        if not (clickable or scrollable or editable or label):
            continue

        key = (label, x1, y1, x2, y2)
        if key in seen:
            continue
        seen.add(key)

        frame.elements.append(
            Element(
                id="pending",
                label=label,
                role=_role(node),
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                enabled=enabled,
                focused=focused,
                editable=editable,
                clickable=clickable,
                scrollable=scrollable,
                password=password,
            )
        )

    # Gán id ổn định trong frame, bỏ phần tử khổng lồ (root) không có nhãn.
    frame.elements = [
        el
        for el in frame.elements
        if (el.label or el.clickable or el.editable or el.scrollable)
        and (el.x2 - el.x1) * (el.y2 - el.y1) < width * height * 0.85
    ]
    for index, el in enumerate(frame.elements, start=1):
        el.id = f"e{index}"

    frame.screen_text = texts
    frame.secure_input = any(el.password for el in frame.elements)

    if screenshot_path:
        try:
            with open(screenshot_path, "wb") as handle:
                proc = subprocess.run(
                    ["adb", "exec-out", "screencap", "-p"],
                    capture_output=True,
                    timeout=20,
                )
                handle.write(proc.stdout)
            frame.screenshot = screenshot_path
        except Exception:
            frame.screenshot = None

    return frame
