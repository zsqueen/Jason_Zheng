"""Read-only end-to-end check using the pet's saved account and model settings."""

import importlib
import sys
import time
from pathlib import Path

from .service import WRITE_TOOLS, BiliService, read_json


def check_panel():
    from PySide6.QtWidgets import QApplication

    pet_module = importlib.import_module("桌宠")
    app = QApplication.instance() or QApplication([])
    pet = pet_module.PetWindow()
    pet.timer.stop()
    pet.reaction_timer.stop()
    panel = pet.bili_panel
    panel.scheduler.stop()
    service = panel.service
    original_request = service._request
    original_config = service.config
    original_scan = service.scan
    forbidden = {tool["function"]["name"] for tool in WRITE_TOOLS}

    def request(name, args):
        if name in forbidden:
            raise PermissionError("Outgoing account operations prohibited during test")
        return original_request(name, args)

    def config():
        return {
            **original_config(),
            "auto_comment": False,
            "dm_mode": "off",
            "triple_mode": "off",
            "dynamic_on": False,
        }

    bvid = "BV16z446yEWp"
    service._request = request
    service.config = config
    service.scan = lambda direction, bv, key, base, model: original_scan(
        direction, bvid, key, base, model
    )
    try:
        panel.scan()
        deadline = time.monotonic() + 500
        while "scan" in panel.jobs and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.05)
        text = panel.report.toPlainText()
        print(
            "UI report chars:",
            len(text),
            "Video present:",
            bvid in text,
            "Chat messages:",
            len(pet.chat_history),
            "Pet busy:",
            pet.ds_busy,
            flush=True,
        )
        if (
            "scan" in panel.jobs
            or bvid not in text
            or len(pet.chat_history) != 2
            or pet.ds_busy
        ):
            raise RuntimeError("Panel scan or pet handoff failed: " + text[:500])
        print(
            "Live panel scan, model summary, persistence and pet chat handoff passed",
            flush=True,
        )
    finally:
        panel.shutdown()
        pet.tray.hide()
        pet.speech_label.hide()


def main():
    if "--panel" in sys.argv:
        check_panel()
        return
    home = Path(__file__).resolve().parent.parent
    pet = importlib.import_module("桌宠")
    config = read_json(home / "config.json", {})
    service = BiliService(home / "bili-data")
    if "--login" in sys.argv:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout

        _app = QApplication.instance() or QApplication([])
        dialog = QDialog()
        dialog.setWindowTitle("大肥鱼 B站登录校验")
        layout = QVBoxLayout(dialog)
        label = QLabel("请用B站App扫码并在手机确认；通过账号校验后继续只读测试。")
        layout.addWidget(label)
        image = QLabel()
        layout.addWidget(image)
        import base64

        try:
            qr = service.api("bili_login_start")
            pixmap = QPixmap()
            pixmap.loadFromData(base64.b64decode(qr["image"]))
            image.setPixmap(pixmap)
            timer = QTimer(dialog)

            def poll():
                try:
                    result = service.api("bili_login_poll")
                    if result["status"] == "done":
                        print("登录凭证已通过真实账号校验", flush=True)
                        timer.stop()
                        dialog.accept()
                    elif result["status"] in ("timeout", "no_session"):
                        timer.stop()
                        label.setText("二维码过期，请关闭窗口并重新运行登录校验。")
                except Exception as exc:
                    timer.stop()
                    label.setText(str(exc))

            timer.timeout.connect(poll)
            timer.start(1500)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                service.close()
                return
        except Exception:
            service.close()
            raise
    original_api = service.api
    original_completion = service.completion

    def api(name, args=None):
        print("B站请求:", name, args, flush=True)
        try:
            result = original_api(name, args)
        except Exception as exc:
            print("B站请求失败:", type(exc).__name__, str(exc)[:500], flush=True)
            raise
        if name == "bili_search":
            print("搜索结果:", len(result.get("videos", [])), flush=True)
        elif name == "bili_subtitle":
            print(
                "字幕字符:",
                len(result.get("text", "")),
                result.get("message", ""),
                flush=True,
            )
        elif name == "bili_comments":
            print("评论条数:", len(result.get("comments", [])), flush=True)
        else:
            print("返回字段:", list(result), flush=True)
        return result

    def completion(*args, **kwargs):
        result = original_completion(*args, **kwargs)
        print(
            "模型工具:",
            [call["function"]["name"] for call in result.get("tool_calls", [])],
            flush=True,
        )
        if not result.get("tool_calls"):
            print("模型报告:", result.get("content"), flush=True)
        return result

    service.api = api
    service.completion = completion
    try:
        service.api("bili_whoami")
        result = service.scan(
            "", "", config.get("ds_api_key", ""), pet.DS_BASE_URL, pet.DS_MODEL
        )
        print("归档成功:", result["bvids"], result["path"], flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    main()
