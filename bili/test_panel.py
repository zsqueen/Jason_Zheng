"""Offscreen Qt checks without real account writes or changes to saved settings."""

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from .panel import BiliPanel


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.pet = QWidget()
        self.pet.cfg = {"ds_api_key": "test"}
        self.pet.ds_busy = False
        self.pet.memory_lock = threading.Lock()
        self.pet.chat_history = []
        self.pet.max_history = 40
        self.speech = []
        self.pet.say = self.speech.append
        self.panel = BiliPanel(self.pet, self.directory.name, "test", "test")
        self.panel.scheduler.stop()

    def tearDown(self):
        self.panel.shutdown()
        self.panel.hide()
        self.directory.cleanup()

    def wait_jobs(self):
        deadline = time.monotonic() + 5
        while self.panel.jobs and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertFalse(self.panel.jobs)

    def test_chat_preserves_full_reply_and_clears_busy(self):
        reply = "完整回复" * 60
        with patch.object(self.panel.service, "chat", return_value=reply):
            self.panel.chat([{"role": "system", "content": "test"}], "question", "test")
            self.wait_jobs()
        self.assertFalse(self.pet.ds_busy)
        self.assertEqual(self.speech[-1], reply)
        self.assertEqual(self.pet.chat_history[-1]["content"], reply)
        self.assertEqual(self.panel.report.toPlainText(), reply)

    def test_incoming_notification_display_memory_and_dedup(self):
        item = {"key": "dm:456:1", "kind": "dm", "uid": "456", "text": "test incoming"}
        with (
            patch.object(
                self.panel.service,
                "status",
                return_value={
                    "logged_in": True,
                    "auto_rounds": 0,
                    "seen_count": 0,
                    "home": "test",
                },
            ),
            patch.object(
                self.panel.service, "api", return_value={"items": [item], "errors": []}
            ),
        ):
            self.panel.inbox()
            self.wait_jobs()
        self.assertIn("test incoming", self.panel.inbox_text.toPlainText())
        self.assertEqual(len(self.pet.chat_history), 2)
        self.assertIn(item["key"], self.panel.service.watch_seen)
        self.assertTrue(any("1条新消息" in line for line in self.speech))

    def test_approval_displays_exact_target_and_denies_by_default(self):
        request = {
            "deadline": time.monotonic() + 60,
            "event": threading.Event(),
            "name": "bili_send_message",
            "args": {"receiver_uid": 456, "text": "exact text"},
            "approved": False,
        }
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ) as question:
            self.panel._approve(request)
        self.assertFalse(request["approved"])
        self.assertTrue(request["event"].is_set())
        text = question.call_args.args[2]
        self.assertIn("456", text)
        self.assertIn("exact text", text)
        self.assertEqual(question.call_args.args[4], QMessageBox.StandardButton.No)
        request["event"].clear()
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            self.panel._approve(request)
        self.assertTrue(request["approved"])

    def test_scheduler_dispatch_and_expired_approval(self):
        with (
            patch.object(
                self.panel.service, "status", return_value={"logged_in": True}
            ),
            patch("bili.panel.due_scan", return_value=True),
            patch("bili.panel.due_dynamic", return_value=False),
            patch.object(self.panel, "scan") as scan,
        ):
            self.panel.tick()
            scan.assert_called_once_with(automatic=True)
        request = {
            "deadline": time.monotonic() - 1,
            "event": threading.Event(),
            "approved": False,
        }
        with patch.object(QMessageBox, "question") as question:
            self.panel._approve(request)
            question.assert_not_called()
        self.assertTrue(request["event"].is_set())

    def test_failed_scan_resets_busy_and_sets_auto_retry(self):
        with (
            patch.object(
                self.panel.service,
                "status",
                return_value={
                    "logged_in": True,
                    "auto_rounds": 0,
                    "seen_count": 0,
                    "home": "test",
                },
            ),
            patch.object(
                self.panel.service, "scan", side_effect=RuntimeError("test failure")
            ),
        ):
            self.panel.scan(automatic=True)
            self.wait_jobs()
        self.assertFalse(self.pet.ds_busy)
        self.assertIn("test failure", self.panel.report.toPlainText())
        self.assertGreater(self.panel.service.state["retry_after"], time.time())


if __name__ == "__main__":
    unittest.main()
