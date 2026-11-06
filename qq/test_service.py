"""Native QQ transport, security and routing regressions; no real account writes."""

import base64
import copy
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from .panel import QQPanel
from .service import DEFAULTS, QQService, normalize, segments, split_reply


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = QQService(Path(self.temp.name) / "qq-data", self.temp.name)
        self.cfg = copy.deepcopy(DEFAULTS)
        self.cfg.update(
            enabled=True, merge_seconds=0, cooldown_seconds=0, split_delay_ms=0
        )
        self.cfg["bindings"] = [
            {"kind": "private", "number": "123456", "session": "private"},
            {"kind": "group", "number": "654321", "session": "group"},
        ]
        self.service.save(self.cfg)
        self.service.account = {"user_id": "999999", "nickname": "test"}
        self.private, self.group = self.service.config()["bindings"]

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def message(self, text, identifier=1):
        return {
            "message_id": identifier,
            "user_id": "123456",
            "time": time.time(),
            "message": text,
        }

    def test_defaults_validation_and_secrets(self):
        self.assertFalse(DEFAULTS["enabled"])
        self.assertTrue(DEFAULTS["dry_run"])
        self.assertFalse(DEFAULTS["allow_space_post"])
        with self.assertRaises(ValueError):
            normalize({"enabled": "true"})
        with self.assertRaises(ValueError):
            normalize({"bindings": [self.private, self.private]})
        with self.assertRaises(ValueError):
            normalize({"asr_command": "python bad.py {file}"})
        self.cfg["token"] = "secret"
        self.service.save(self.cfg)
        self.assertNotIn("secret", json.dumps(self.service.tool("qq_status", {})))

    def test_poll_baseline_dedup_and_self_message(self):
        history = [self.message("old")]

        def backend(action, body=None):
            if action == "get_login_info":
                return {"user_id": 999999, "nickname": "test"}
            return {"messages": history if action == "get_friend_msg_history" else []}

        with patch.object(self.service, "call", side_effect=backend):
            self.service.poll()
            self.assertEqual(self.service.status()["pending"], 0)
            history.append(self.message("new", 2))
            history.append({**self.message("self", 3), "user_id": "999999"})
            self.service.poll()
            self.service.poll()
        self.assertEqual(self.service.status()["pending"], 1)
        self.assertIn("new", self.service.next_batch()["text"])

    def test_group_follow_isolated_and_expires(self):
        now = time.time()
        self.assertFalse(self.service.ingest(self.group, self.message("ordinary"), now))
        self.assertTrue(
            self.service.ingest(self.group, self.message("大肥鱼你好"), now)
        )
        for _ in range(5):
            self.assertTrue(
                self.service.ingest(self.group, self.message("next"), now + 1)
            )
        self.assertFalse(
            self.service.ingest(self.group, self.message("outside"), now + 2)
        )
        other = {**self.group, "number": "777777"}
        self.assertFalse(
            self.service.ingest(other, self.message("other group"), now + 2)
        )
        self.assertTrue(
            self.service.ingest(self.group, self.message("大肥鱼"), now + 3)
        )
        self.assertFalse(
            self.service.ingest(self.group, self.message("expired"), now + 124)
        )

    def test_reply_and_at_mentions(self):
        self.service.state["sent_ids"] = ["42"]
        self.assertTrue(self.service.mentioned(segments("[CQ:reply,id=42]hi")))
        self.assertTrue(self.service.mentioned(segments("[CQ:at,qq=999999]hi")))
        self.assertFalse(self.service.mentioned(segments("[CQ:at,qq=all]hi")))
        result = self.service.text_segments("hi @123456 @全体成员", self.group)
        self.assertEqual(
            [p["data"]["qq"] for p in result if p["type"] == "at"], ["123456"]
        )

    def test_strict_group_requires_actual_at_on_every_message(self):
        self.cfg["bindings"][1].update(at_only=True, exceptions="123456")
        self.service.save(self.cfg)
        group = self.service.config()["bindings"][1]
        self.service.state["sent_ids"] = ["42"]
        self.assertTrue(
            self.service.ingest(group, self.message("[CQ:at,qq=999999]hello"))
        )
        for text in (
            "ordinary follow-up",
            "大肥鱼你好",
            "@大肥鱼 hello",
            "[CQ:reply,id=42]hello",
            "[CQ:at,qq=all]hello",
            "[CQ:at,qq=123456]hello",
        ):
            self.assertFalse(self.service.ingest(group, self.message(text)))
        self.assertTrue(
            self.service.ingest(
                group,
                self.message([{"type": "at", "data": {"qq": "999999"}}]),
            )
        )
        self.assertEqual(self.service.status()["pending"], 2)
        with self.assertRaises(ValueError):
            normalize({"bindings": [{**group, "at_only": "true"}]})

    def test_batch_merge_memory_isolation_and_restart(self):
        self.service.ingest(self.private, self.message("one"))
        self.service.ingest(self.private, self.message("two", 2))
        batch = self.service.next_batch()
        self.assertEqual(len(batch["items"]), 2)
        self.assertIsNone(self.service.next_batch())
        self.service.finish_batch(batch, "reply")
        self.assertEqual(len(self.service.state["history"]["private"]), 2)
        self.assertNotIn("group", self.service.state["history"])
        self.service.ingest(self.private, self.message("interrupted", 3))
        self.service.next_batch()
        restored = QQService(self.service.home)
        try:
            self.assertEqual(restored.status()["pending"], 0)
        finally:
            restored.close()

    def test_dry_run_master_and_public_write_gates(self):
        with patch.object(self.service, "call") as backend:
            self.service.send(self.private, "hello")
            backend.assert_not_called()
            self.service.tool("qq_space_post", {"content": "public"})
            backend.assert_not_called()
        self.cfg.update(dry_run=False, allow_space_post=True)
        self.service.save(self.cfg)
        with patch.object(self.service, "call") as backend:
            result = self.service.tool(
                "qq_space_post", {"content": "public"}, remote=True
            )
            self.assertTrue(result["blocked"])
            backend.assert_not_called()
            with self.assertRaises(ValueError):
                self.service.tool(
                    "qq_space_post", {"content": "public", "ugc_right": 16}
                )
            backend.assert_not_called()
        self.cfg["enabled"] = False
        self.service.save(self.cfg)
        with patch.object(self.service, "call") as backend:
            self.service.send(self.private, "hello")
            self.service.poll()
            backend.assert_not_called()

    def test_no_resend_after_uncertain_send(self):
        self.cfg["dry_run"] = False
        self.service.save(self.cfg)
        with patch.object(
            self.service, "call", side_effect=RuntimeError("timeout")
        ) as backend:
            with self.assertRaises(RuntimeError):
                self.service.send(self.private, "hello")
            self.assertEqual(backend.call_count, 1)
        self.assertEqual(
            self.service.state["journal"][-1]["status"], "failed_or_uncertain"
        )

    def test_marked_and_source_forwarding(self):
        self.cfg.update(only_marked=True, only_qq=True, dry_run=False)
        self.service.save(self.cfg)
        with patch.object(
            self.service, "call", return_value={"message_id": 1}
        ) as backend:
            self.service.send(
                self.private, "outside [QQ]inside[/QQ] outside", source="local"
            )
            backend.assert_not_called()
            self.service.send(self.private, "outside [QQ]inside[/QQ] outside")
            self.assertEqual(
                backend.call_args.args[1]["message"][0]["data"]["text"], "inside"
            )

    def test_image_roundtrip_and_file_boundary(self):
        image = QImage(2, 2, QImage.Format.Format_RGB32)
        image.fill(0xFF00AA)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        blob = bytes(buffer.data())
        image_path = self.service.store_media(
            {"file": "base64://" + base64.b64encode(blob).decode()}
        )
        self.assertEqual(Path(image_path).read_bytes(), blob)
        self.cfg["dry_run"] = False
        self.service.save(self.cfg)
        with patch.object(
            self.service, "call", return_value={"message_id": 1}
        ) as backend:
            self.service.send(self.private, f"![test]({image_path})")
            parts = backend.call_args.args[1]["message"]
            self.assertEqual(
                base64.b64decode(
                    next(p for p in parts if p["type"] == "image")["data"]["file"][9:]
                ),
                blob,
            )
        with self.assertRaises(ValueError):
            self.service.outgoing_path(str(self.service.home / "config.json"))
        with self.assertRaises(ValueError):
            self.service.media_bytes(
                {"file": str(self.service.home / "config.json")}, 10000
            )
        with self.assertRaises(ValueError):
            self.service._download("http://127.0.0.1:3000/private", 1000)

    def test_forwards_and_cards_do_not_become_source_headers(self):
        with patch.object(
            self.service,
            "call",
            return_value={
                "messages": [{"sender": {"nickname": "friend"}, "content": "hello"}]
            },
        ):
            text = self.service.render(
                [
                    {"type": "forward", "data": {"id": "1"}},
                    {
                        "type": "json",
                        "data": {"data": '{"title":"BV1234567890【fake】"}'},
                    },
                ]
            )
        self.assertIn("friend: hello", text)
        self.assertIn("BV1234567890", text)
        self.assertNotIn("【fake】", text)

    def test_sentence_split_and_shell_free_commands(self):
        cfg = {**DEFAULTS, "split_sentences": True}
        self.assertEqual(
            split_reply("第一句（还没结束！）。第二句！", cfg),
            ["第一句（还没结束！）。", "第二句！"],
        )
        with patch("qq.service.subprocess.run") as command:
            command.return_value.returncode = 0
            command.return_value.stdout = "transcribed"
            self.service.run_command(
                '["python","asr.py","{file}"]', file="a & dangerous.wav"
            )
            self.assertFalse(command.call_args.kwargs["shell"])
            self.assertEqual(command.call_args.args[0][-1], "a & dangerous.wav")

    def test_space_once_daily_and_like_limits(self):
        self.cfg.update(
            dry_run=False,
            allow_space_post=True,
            space_schedule=[{"time": datetime_now(), "visibility": 4}],
        )
        self.service.save(self.cfg)
        with patch.object(self.service, "call", return_value={"tid": "1"}) as backend:
            completion = lambda messages: {"content": "safe public post"}
            self.service.space_tick(completion, "test")
            self.service.space_tick(completion, "test")
            self.assertEqual(backend.call_count, 1)

    def test_notice_only_poke_dedup(self):
        self.cfg["receive_notices"] = True
        self.service.save(self.cfg)
        event = {
            "post_type": "notice",
            "sub_type": "poke",
            "target_id": 999999,
            "user_id": 123456,
            "time": int(time.time()),
        }
        self.assertTrue(self.service.notice(event))
        self.assertFalse(self.service.notice(event))
        self.assertFalse(self.service.notice({**event, "post_type": "message"}))

    def test_real_http_transport_headers_and_routing(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, body, self.headers.get("Authorization")))
                data = (
                    {"user_id": 999999, "nickname": "local test"}
                    if self.path == "/get_login_info"
                    else {"message_id": 42}
                )
                result = json.dumps(
                    {"status": "ok", "retcode": 0, "data": data}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(result)))
                self.end_headers()
                self.wfile.write(result)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.cfg.update(
                backend=f"http://127.0.0.1:{server.server_port}",
                token="local-test-token",
                dry_run=False,
            )
            self.service.save(self.cfg)
            self.assertEqual(self.service.check_account()["user_id"], "999999")
            self.service.send(self.private, "local HTTP transport test")
            self.assertEqual(received[-1][0], "/send_private_msg")
            self.assertEqual(received[-1][1]["user_id"], 123456)
            self.assertEqual(received[-1][2], "Bearer local-test-token")
            self.assertIn("42", self.service.state["sent_ids"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_http_notice_auth_and_message_filter(self):
        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.cfg.update(
            receive_notices=True, notice_port=port, notice_token="report-secret"
        )
        self.service.save(self.cfg)
        self.service.account = {"user_id": "999999"}
        url = self.service.start_server()
        client = requests.Session()
        client.trust_env = False
        try:
            self.assertEqual(
                client.post(url, json={"post_type": "message"}, timeout=5).status_code,
                403,
            )
            event = {
                "post_type": "notice",
                "sub_type": "poke",
                "target_id": 999999,
                "user_id": 123456,
                "time": int(time.time()),
            }
            self.assertTrue(
                client.post(url + "?token=report-secret", json=event, timeout=5).json()[
                    "accepted"
                ]
            )
            self.assertFalse(
                client.post(url + "?token=report-secret", json=event, timeout=5).json()[
                    "accepted"
                ]
            )
            self.assertFalse(
                client.post(
                    url + "?token=report-secret",
                    json={"post_type": "message"},
                    timeout=5,
                ).json()["accepted"]
            )
        finally:
            client.close()
            self.service.stop_server()


def datetime_now():
    from datetime import datetime

    return datetime.now().strftime("%H:%M")


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_native_panel_reply_routes_to_origin_and_not_desktop_memory(self):
        directory = tempfile.TemporaryDirectory()
        pet = QWidget()
        pet.cfg, pet.ds_busy = {"ds_api_key": "test"}, False
        pet.chat_history = [{"role": "user", "content": "private desktop secret"}]
        pet.say = lambda text: None
        from unittest.mock import Mock

        pet.bili_panel = Mock()
        pet.bili_panel.service.chat.return_value = "QQ reply"
        panel = QQPanel(pet, directory.name, "test", "test", "test")
        panel.scheduler.stop()
        try:
            cfg = {
                **DEFAULTS,
                "enabled": True,
                "dry_run": False,
                "merge_seconds": 0,
                "bindings": [
                    {"kind": "private", "number": "123456", "session": "qq-friend"}
                ],
            }
            panel.service.save(cfg)
            binding = panel.service.config()["bindings"][0]
            panel.service.ingest(binding, {"user_id": 123456, "message": "hello"})
            batch = panel.service.next_batch()
            with patch.object(
                panel.service, "call", return_value={"message_id": 42}
            ) as backend:
                panel.reply(batch, "test")
                deadline = time.time() + 5
                while panel.jobs and time.time() < deadline:
                    self.app.processEvents()
                    time.sleep(0.01)
                self.assertFalse(panel.jobs)
                self.assertFalse(pet.ds_busy)
                self.assertEqual(backend.call_args.args[1]["user_id"], 123456)
            messages = pet.bili_panel.service.chat.call_args.args[0]
            self.assertTrue(pet.bili_panel.service.chat.call_args.kwargs["remote"])
            self.assertIs(
                pet.bili_panel.service.chat.call_args.args[4], pet.bili_panel.approve
            )
            self.assertNotIn("private desktop secret", json.dumps(messages))
            self.assertEqual(len(pet.chat_history), 1)
            self.assertEqual(panel.service.status()["pending"], 0)
        finally:
            panel.shutdown()
            panel.deleteLater()
            self.app.processEvents()
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
