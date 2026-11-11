"""Exercise QQ panel routing with real model/Bilibili, without QQ writes."""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from PySide6.QtWidgets import QApplication, QWidget
from bili.service import BiliService, read_json
from qq.panel import QQPanel
from qq.service import DEFAULTS
import importlib

pet_module = importlib.import_module("桌宠")
app = QApplication([])
pet = QWidget()
pet.cfg = read_json(root / "config.json", {})
pet.ds_busy = False
pet.say = lambda text: None
service = BiliService(root / "bili-data")
from types import SimpleNamespace

pet.bili_panel = SimpleNamespace(service=service, approve=lambda name, args: False)
calls = []
original = service.api


def api(name, args=None):
    calls.append(name)
    return original(name, args)


service.api = api
with tempfile.TemporaryDirectory() as directory:
    panel = QQPanel(
        pet,
        directory,
        pet_module.DS_BASE_URL,
        pet_module.DS_MODEL,
        pet_module.DS_SYSTEM,
    )
    panel.scheduler.stop()
    cfg = dict(DEFAULTS, enabled=True, dry_run=True, merge_seconds=0)
    cfg["bindings"] = [
        {
            "kind": "group",
            "number": "747869735",
            "session": "check",
            "mention_only": False,
        }
    ]
    panel.service.save(cfg)
    panel.service.ingest(
        panel.service.config()["bindings"][0],
        {
            "user_id": 123456,
            "message": "去刷五分钟b站回来，告诉我你学到些什么",
        },
    )
    batch = panel.service.next_batch()
    with patch.object(panel.service, "send", return_value={"dry_run": True}) as send:
        panel.reply(batch, pet.cfg["ds_api_key"])
        deadline = time.time() + 500
        while panel.jobs and time.time() < deadline:
            app.processEvents()
            time.sleep(0.05)
        print("Real Bilibili tools called:", calls)
        print("QQ reply ready:", send.called)
        print("Task logs:", list(panel.service.logs))
        if send.called:
            print("Reply:", send.call_args.args[1])
        passed = bool(calls) and send.called and not panel.jobs
    panel.shutdown()
service.close()
if not passed:
    raise SystemExit("Real model-to-Bilibili QQ routing verification failed.")
