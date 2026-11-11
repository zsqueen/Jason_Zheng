"""Switch the authorized group to actual-mention-only and discard old work."""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qq.service import QQService

home = Path(__file__).resolve().parent
backup = home / "config.before-strict-at.json"
if not backup.exists():
    shutil.copy2(home / "config.json", backup)
service = QQService(home)
cfg = service.config()
for binding in cfg["bindings"]:
    if binding["kind"] == "group" and binding["number"] == "747869735":
        binding.update(at_only=True, mention_only=True, exceptions="")
service.save(cfg)
service.state["pending"] = [
    item for item in service.state["pending"] if item["chat"] != "group:747869735"
]
service.state["seen"].pop("group:747869735", None)
service.persist()
service.poll()
if "group:747869735" not in service.state["seen"]:
    cfg["enabled"] = False
    service.save(cfg)
    raise SystemExit("Baseline failed; paused automatic replies.")
print("Strict actual-mention-only enabled; old queue cleared and baseline refreshed.")
