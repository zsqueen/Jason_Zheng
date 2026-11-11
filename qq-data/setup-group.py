"""Apply the authorized group binding and send its single journaled test."""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qq.service import QQService

home = Path(__file__).resolve().parent
marker = home / "group-test-747869735.json"
if marker.exists():
    raise SystemExit("Test already attempted; never automatically resend.")
shutil.copy2(home / "config.json", home / "config.before-group-747869735.json")
service = QQService(home)
service.check_account()
cfg = service.config()
if cfg["bindings"]:
    raise SystemExit("Existing bindings preserved; inspect before changing.")
cfg.update(
    {
        "enabled": True,
        "dry_run": False,
        "mention_keywords": "",
        "bindings": [
            {
                "kind": "group",
                "number": "747869735",
                "session": "qq-group-747869735",
                "name": "authorized-test-group",
                "enabled": True,
                "mention_only": True,
                "gate": False,
            }
        ],
    }
)
service.save(cfg)
service.poll()
if "group:747869735" not in service.state["seen"]:
    cfg["enabled"] = False
    service.save(cfg)
    raise SystemExit("Baseline failed; automatic replies remain disabled.")
marker.write_text(json.dumps({"status": "attempting"}), encoding="utf-8")
result = service.send(service.binding("group:747869735"), "大肥鱼连接测试")
marker.write_text(
    json.dumps({"status": "backend_confirmed", "result": result}), encoding="utf-8"
)
print("Baseline established; group-only automatic replies enabled.")
print("Test backend response:", result)
for item in result:
    if isinstance(item, dict) and item.get("message_id"):
        message = service.call("get_msg", {"message_id": item["message_id"]})
        print("Readback sender:", message.get("sender", {}).get("user_id"))
        print("Readback group:", message.get("group_id"))
        print("Readback text:", message.get("raw_message"))
