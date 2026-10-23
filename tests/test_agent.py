"""Test vòng lặp agent với Jev giả + adb giả (không gọi mạng, không cần máy)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cua import agent
from cua.observe import Element, Frame


def el(
    label="Đăng nhập",
    role="button",
    x=200,
    y=400,
    editable=False,
    focused=False,
    clickable=True,
    password=False,
) -> Element:
    return Element(
        id="e1",
        label=label,
        role=role,
        x1=x - 40,
        y1=y - 20,
        x2=x + 40,
        y2=y + 20,
        enabled=True,
        focused=focused,
        editable=editable,
        clickable=clickable,
        password=password,
    )


def frame(elements, package="com.test.app") -> Frame:
    return Frame(
        package=package,
        width=1080,
        height=2400,
        elements=elements,
        screen_text=[e.label for e in elements if e.label],
    )


class SeqObserver:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    def __call__(self, path=None):
        current = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return current


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def tap(self, element):
        self.calls.append(("tap", element.label))

    def tap_point(self, x, y):
        self.calls.append(("tap_point", x, y))

    def type_text(self, value):
        self.calls.append(("type", value))

    def back(self):
        self.calls.append(("back",))

    def scroll(self, direction, current_frame, element=None):
        self.calls.append(("scroll", direction))


def answers(
    operation,
    prob=0.95,
    conf=0.9,
    target="e1",
    target_prob=0.95,
    verified=0.05,
    consequential=0.0,
    authorized=0.0,
    direction="down",
):
    return {
        "answers": {
            "nextOperation": {
                "type": "choice",
                "choice": operation,
                "confidence": conf,
                "probabilities": {operation: prob},
            },
            "tapTarget": {
                "type": "choice",
                "choice": target,
                "confidence": 0.9,
                "probabilities": {target: target_prob},
            },
            "scrollDirection": {
                "type": "choice",
                "choice": direction,
                "confidence": 0.9,
                "probabilities": {direction: 0.9},
            },
            "completionVerified": {"type": "noul", "noul": verified},
            "consequential": {"type": "noul", "noul": consequential},
            "explicitAuthorization": {"type": "noul", "noul": authorized},
        }
    }


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.trace_dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def run_agent(self, decide, observer, executor, **kwargs):
        return agent.run(
            "kiểm tra màn hình",
            None,
            decide=decide,
            observer=observer,
            executor=executor,
            trace_dir=self.trace_dir,
            **kwargs,
        )

    def test_bam_roi_done_khi_man_hinh_chung_minh_xong(self):
        login = frame([el(label="Đăng nhập")])
        home = frame([el(label="Tổng quan", role="text")])

        script = [
            answers("tap", prob=0.96),
            answers("DONE", prob=0.99, verified=0.95),
        ]

        def decide(state, questions):
            return script.pop(0) if script else answers("DONE", prob=0.99, verified=0.95)

        executor = FakeExecutor()
        result = self.run_agent(
            decide,
            SeqObserver([login, login, home]),
            executor,
        )

        self.assertTrue(result.ok, result.reason)
        self.assertEqual(executor.calls, [("tap", "Đăng nhập")])

    def test_hanh_dong_co_he_qua_thieu_cho_phep_thi_khong_bam(self):
        dangerous = frame([el(label="Xoá quán")])
        executor = FakeExecutor()

        def decide(state, questions):
            return answers("tap", prob=0.7, conf=0.5, consequential=0.95, authorized=0.2)

        result = self.run_agent(decide, SeqObserver([dangerous]), executor, max_steps=6)

        self.assertFalse(result.ok)
        self.assertEqual(executor.calls, [])

    def test_done_khong_du_bang_chung_thi_khong_chap_nhan(self):
        home = frame([el(label="Tổng quan", role="text")])
        executor = FakeExecutor()

        def decide(state, questions):
            # Xác suất DONE rất cao nhưng màn hình không chứng minh hoàn thành.
            return answers("DONE", prob=0.99, verified=0.3)

        result = self.run_agent(decide, SeqObserver([home]), executor, max_steps=6)

        self.assertFalse(result.ok)
        self.assertIn("stuck", result.reason)

    def test_muc_tieu_bien_mat_truoc_khi_bam_thi_khong_bam(self):
        before = frame([el(label="Tiếp")])
        after = frame([el(label="Màn hình khác", role="text")])

        # Lần 1 chọn bấm; sau khi màn hình đổi, model thấy không còn mục tiêu
        # nên dừng — mô phỏng đúng vòng observe → decide.
        script = [answers("tap"), answers("BLOCKED", prob=0.9)]

        def decide(state, questions):
            return script.pop(0) if script else answers("BLOCKED", prob=0.9)

        executor = FakeExecutor()
        result = self.run_agent(
            decide,
            SeqObserver([before, after, after]),
            executor,
            max_steps=5,
        )

        self.assertFalse(result.ok)
        self.assertEqual(executor.calls, [])

    def test_go_du_lieu_vao_truong_dang_focus(self):
        form = frame([el(label="Email", role="text field", editable=True, focused=True)])
        home = frame([el(label="Tổng quan", role="text")])

        script = [
            answers("typeText"),
            answers("DONE", prob=0.99, verified=0.95),
        ]

        def decide(state, questions):
            return script.pop(0)

        executor = FakeExecutor()
        result = self.run_agent(
            decide,
            SeqObserver([form, form, home]),
            executor,
            fills={"Email": "quan@test.vn"},
        )

        self.assertTrue(result.ok, result.reason)
        self.assertIn(("type", "quan@test.vn"), executor.calls)

    def test_chi_moi_type_text_khi_co_du_lieu_cho_truong_dang_focus(self):
        form = frame([el(label="Email", role="text field", editable=True, focused=True)])

        self.assertIn("typeText", agent.legal_operations(form, {"Email": "x@y.z"}))
        self.assertNotIn("typeText", agent.legal_operations(form, {}))
        self.assertNotIn(
            "typeText",
            agent.legal_operations(form, {"Số điện thoại": "0901"}),
        )

    def test_ket_thuc_khi_bang_chung_xuat_hien_tren_man_hinh(self):
        login = frame([el(label="Đăng nhập")])
        wallet = frame([el(label="Ví & Thu nhập", role="text")])

        def decide(state, questions):
            return answers("tap")

        executor = FakeExecutor()
        result = agent.run(
            "mở ví",
            None,
            decide=decide,
            observer=SeqObserver([login, login, wallet]),
            executor=executor,
            expect=["Ví & Thu nhập"],
            trace_dir=self.trace_dir,
        )

        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.reason, "expect-satisfied")
        self.assertEqual(executor.calls, [("tap", "Đăng nhập")])

    def test_model_no_xong_nhung_thieu_bang_chung_thi_khong_chap_nhan(self):
        home = frame([el(label="Tổng quan", role="text")])

        def decide(state, questions):
            return answers("DONE", prob=0.99, verified=0.99)

        result = agent.run(
            "mở ví",
            None,
            decide=decide,
            observer=SeqObserver([home]),
            executor=FakeExecutor(),
            expect=["Ví & Thu nhập"],
            max_steps=6,
            trace_dir=self.trace_dir,
        )

        self.assertFalse(result.ok)
        self.assertIn("stuck", result.reason)

    def test_replay_bam_theo_toa_do_va_kiem_tra_cuoi(self):
        end = frame([el(label="Ví & Thu nhập", role="text")])
        executor = FakeExecutor()
        plan = {
            "screen": "1080x2400",
            "actions": [
                {"op": "tap", "label": "Đăng nhập", "role": "button", "x": 200, "y": 400},
            ],
        }

        result = agent._replay(
            plan,
            expect=["Ví & Thu nhập"],
            observer=SeqObserver([end]),
            executor=executor,
            package=None,
        )

        self.assertIsNotNone(result)
        self.assertEqual(executor.calls, [("tap_point", 200, 400)])

    def test_replay_tra_ve_none_khi_sai_ket_qua(self):
        end = frame([el(label="Màn hình khác", role="text")])
        plan = {
            "screen": "1080x2400",
            "actions": [
                {"op": "tap", "label": "Đăng nhập", "role": "button", "x": 200, "y": 400},
            ],
        }

        result = agent._replay(
            plan,
            expect=["Ví & Thu nhập"],
            observer=SeqObserver([end]),
            executor=FakeExecutor(),
            package=None,
        )

        self.assertIsNone(result)

    def test_package_khac_thi_dung_ngay(self):
        other = frame([el(label="App khác")], package="com.other.app")
        executor = FakeExecutor()

        def decide(state, questions):
            return answers("tap")

        result = agent.run(
            "kiểm tra",
            "com.test.app",
            decide=decide,
            observer=SeqObserver([other]),
            executor=executor,
            trace_dir=self.trace_dir,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "foreground-mismatch")
        self.assertEqual(executor.calls, [])


if __name__ == "__main__":
    unittest.main()
