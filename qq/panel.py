"""Native Qt QQ controls and worker-to-main-thread handoff."""

import json
import os
import threading
import time

import requests

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .service import DEFAULTS, LIMITS, QQ_TOOLS, QQService

LABELS = {
    "enabled": "QQ总开关",
    "dry_run": "试运行（只记录，不发送）",
    "backend": "OneBot HTTP地址",
    "token": "后端访问令牌",
    "bindings": "聊天绑定（JSON数组）",
    "poll_ms": "轮询间隔（毫秒）",
    "receive_images": "接收图片",
    "send_images": "发送图片/贴纸",
    "max_images": "每批最多收图张数",
    "image_mb": "单张图片上限（MB）",
    "send_files": "发送Markdown本地文件链接",
    "file_mb": "文件/音频上限（MB）",
    "files_private_only": "文件只发私聊",
    "image_root": "额外允许发送的媒体目录（留空不授权）",
    "mention_keywords": "群点名关键词（逗号分隔）",
    "listen_all": "新绑定默认听全群",
    "follow_messages": "点名后接听条数（0关闭）",
    "follow_seconds": "点名后接听秒数",
    "reply_probability": "普通群消息回复概率（%）",
    "mention_always": "点名必回，不掷骰子",
    "cooldown_seconds": "回复冷却（秒）",
    "per_minute": "每个聊天每分钟最多回复批数",
    "merge_seconds": "同一个人消息合并窗口（秒）",
    "merge_max_seconds": "最多等待合并（秒）",
    "merge_count": "一次最多合并消息数",
    "backlog_minutes": "待处理消息有效期（分钟）",
    "only_marked": "只发送[QQ]…[/QQ]标记内正文",
    "only_qq": "只推送QQ唤醒的回复",
    "forward_automatic": "允许推送自动任务结果",
    "wake_tail_seconds": "QQ唤醒后续回复窗口（秒）",
    "split_paragraphs": "长回复按空行分段",
    "split_sentences": "按句子分段",
    "split_delay_ms": "分段发送间隔（毫秒）",
    "allow_at_all": "允许@全体成员",
    "source_header": "添加可信来源头",
    "private_signature": "私聊来源署名",
    "persona_enabled": "启用QQ人设",
    "persona": "全局QQ人设（各绑定可覆盖）",
    "asr_enabled": "语音转文字",
    "asr_command": "转写命令（JSON参数数组，含{file}）",
    "asr_model_dir": "转写模型目录（{model}）",
    "command_timeout": "音频命令超时（秒）",
    "tts_mode": "回复语音合成方式",
    "tts_command": "语音合成命令（JSON数组，含{text}/{file}）",
    "voice_segments": "每段分别发送语音（关=完整一条）",
    "receive_notices": "接收戳一戳和本机注入（HTTP上报）",
    "notice_port": "本机上报端口",
    "notice_token": "上报口令（启用时必填）",
    "allow_space_post": "允许发布QQ空间说说",
    "space_schedule": "空间定时发布（JSON数组，本地时间）",
    "space_watch": "定时查看好友动态",
    "space_interval_minutes": "查看动态间隔（分钟）",
    "space_like": "允许空间点赞（自动每轮3/每天20）",
    "space_comment": "允许空间评论（公开发言）",
    "sticker_enabled": "启用大肥鱼表情包",
    "sticker_probability": "表情包发送概率（%）",
    "proactive_enabled": "允许主动发起私聊",
    "proactive_interval_minutes": "主动私聊间隔（分钟）",
    "at_proactive_enabled": "允许定时@群友发起话题",
    "at_proactive_interval_minutes": "@群友间隔（分钟）",
}


class Bridge(QObject):
    finished = Signal(object)
    approval = Signal(object)


class QQPanel(QDialog):
    def __init__(self, pet, directory, base, model, system):
        super().__init__(pet)
        self.pet, self.base, self.model, self.system = pet, base, model, system
        self.service = QQService(directory, os.path.dirname(directory))
        self.jobs, self.approvals = set(), []
        self.poll_due, self.space_due = 0, time.time() + 30
        self.bridge = Bridge(self)
        self.bridge.finished.connect(self._finished)
        self.bridge.approval.connect(self._approve)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.setWindowTitle("大肥鱼 · QQ")
        self.resize(780, 760)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        row = QHBoxLayout()
        for title, callback in (
            ("检查QQ登录", self.check_account),
            ("现在收一轮", self.poll),
            ("真实发送测试句", self.test_send),
            ("打开QQ后端登录页", self.open_backend),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.tabs.addTab(self.report, "消息与日志")
        settings = QWidget()
        form = QFormLayout(settings)
        note = QLabel(
            "先启动NapCat/SnowLuma并在它的网页扫码登录QQ，再开启OneBot HTTP（通常3000）。\n"
            "新绑定第一次只建立历史基线，请之后再发消息测试。总开关关闭、试运行开启是安全默认。\n"
            "每条绑定的session就是肥鱼的独立QQ记忆名，不需要DSH会话；填desktop可把本地聊天回复推到该聊天。\n"
            "QQ记忆不读取本地聊天或屏幕；空间发言默认关闭，开启即授权定时公开发言。\n"
            "文件发送只允许qq-data/outbox、已收媒体、sprites/_stickers和明确授权的媒体目录。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        example = QLabel(
            '绑定例：[{"kind":"private","number":"123456789","session":"qq-friend","name":"主人","enabled":true}, '
            '{"kind":"group","number":"987654321","session":"qq-group","mention_only":true,"gate":true}]\n'
            "可选：at_only=true（严格只处理实际@自己的消息，忽略关键词、引用、免点名和跟聊）、persona（独立人设）、exceptions（群免点名QQ号，逗号分隔）。相同session共享QQ上下文，请勿把私人会话和公开群绑定到同名。\n"
            '空间定时例：[{"time":"20:30","visibility":4,"enabled":true}]，1=所有人，4=好友，64=仅自己。'
        )
        example.setWordWrap(True)
        example.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(example)
        self.fields = {}
        cfg = self.service.config()
        for key, default in DEFAULTS.items():
            if key in ("tts_mode", "private_signature"):
                field = QComboBox()
                choices = (
                    [
                        ("关闭", "off"),
                        ("Windows系统语音（不录麦克风）", "windows"),
                        ("自定义命令", "command"),
                    ]
                    if key == "tts_mode"
                    else [("不加", "off"), ("[QQ]前缀", "prefix"), ("称呼署名", "name")]
                )
                for title, value in choices:
                    field.addItem(title, value)
                field.setCurrentIndex(field.findData(cfg[key]))
            elif isinstance(default, bool):
                field = QCheckBox()
                field.setChecked(cfg[key])
            elif isinstance(default, int):
                field = QSpinBox()
                field.setRange(*LIMITS[key])
                field.setValue(cfg[key])
            elif isinstance(default, list) or key == "persona":
                field = QTextEdit()
                field.setMaximumHeight(130)
                field.setPlainText(
                    json.dumps(cfg[key], ensure_ascii=False, indent=2)
                    if isinstance(default, list)
                    else cfg[key]
                )
            else:
                field = QLineEdit(cfg[key])
                if key in ("token", "notice_token"):
                    field.setEchoMode(QLineEdit.EchoMode.Password)
            self.fields[key] = field
            form.addRow(LABELS[key], field)
        save = QPushButton("保存QQ设置")
        save.clicked.connect(self.save_settings)
        form.addRow(save)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(settings)
        self.tabs.addTab(scroll, "设置")
        audio_note = QLabel(
            '转写命令例：["D:/path/python.exe","D:/path/asr.py","{file}","--model-dir","{model}"]\n'
            "只运行明确配置的命令，不启用shell，不把QQ文本拼成命令。可接SenseVoice/Whisper等本地转写器。\n"
            '自定义语音例：["D:/path/python.exe","D:/path/tts.py","--text","{text}","--output","{file}"]\n'
            "脚本须生成WAV文件；Windows系统语音无需额外TTS服务。QQ后端仍须支持语音条。"
        )
        audio_note.setWordWrap(True)
        layout.addWidget(audio_note)
        self.scheduler = QTimer(self)
        self.scheduler.timeout.connect(self.tick)
        self.scheduler.start(500)
        self.refresh()
        try:
            self.service.start_server()
        except Exception as exc:
            self.service.log("HTTP上报未启动：" + str(exc))

    def run(self, name, work, callback=None):
        if name in self.jobs or self.service.closed:
            return False
        self.jobs.add(name)

        def worker():
            value, error = None, None
            try:
                value = work()
            except Exception as exc:
                error = str(exc)
            self.bridge.finished.emit((name, callback, value, error))

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _finished(self, result):
        name, callback, value, error = result
        self.jobs.discard(name)
        if self.service.closed:
            return
        if error:
            self.service.log(error)
        if callback:
            callback(value, error)
        self.refresh()

    def refresh(self):
        status = self.service.status()
        account = status["account"]
        self.status_label.setText(
            f"{'QQ已开启' if status['enabled'] else 'QQ关闭'} · {'试运行' if status['dry_run'] else '真实发送'} · "
            f"QQ：{account.get('nickname', '尚未检查')} {account.get('user_id', '')} · 排队 {status['pending']}\n"
            f"数据：{status['home']}\n上报：http://127.0.0.1:{self.service.config()['notice_port']}/qq/notice?token=<上报口令>"
        )
        self.report.setPlainText("\n".join(status["logs"]))

    def save_settings(self):
        try:
            values = {}
            for key, field in self.fields.items():
                if isinstance(field, QCheckBox):
                    values[key] = field.isChecked()
                elif isinstance(field, QSpinBox):
                    values[key] = field.value()
                elif isinstance(field, QComboBox):
                    values[key] = field.currentData()
                elif isinstance(field, QTextEdit):
                    values[key] = (
                        json.loads(field.toPlainText())
                        if isinstance(DEFAULTS[key], list)
                        else field.toPlainText()
                    )
                else:
                    values[key] = field.text().strip()
            from .service import normalize

            values = normalize(values)
            old = self.service.config()
            public = [
                key
                for key in ("allow_space_post", "space_like", "space_comment")
                if values[key] and not old[key]
            ]
            real = (
                values["enabled"]
                and not values["dry_run"]
                and (not old["enabled"] or old["dry_run"])
            )
            if public or real:
                answer = QMessageBox.question(
                    self,
                    "授权QQ账号操作",
                    "将以登录的QQ号自动回复绑定聊天。\n新开公开功能："
                    + ", ".join(public)
                    + "\n消息内容会发往配置的模型服务，公开内容发出后需自行到QQ删除。是否授权？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            if values["receive_notices"] and not values["notice_token"]:
                raise ValueError("启用上报必须设置口令")
            self.service.save(values)
            self.service.stop_server()
            self.service.start_server()
            self.poll_due = 0
            self.service.log("QQ设置已保存")
        except Exception as exc:
            QMessageBox.warning(self, "QQ设置", str(exc))
        self.refresh()

    def check_account(self):
        self.run("account", self.service.check_account)

    def poll(self):
        self.run("poll", self.service.poll)

    def open_backend(self):
        from urllib.parse import urlparse

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        endpoint = urlparse(self.service.config()["backend"])
        host = endpoint.hostname or "127.0.0.1"
        QDesktopServices.openUrl(QUrl(f"http://{host}:6099"))

    def test_send(self):
        bindings = [b for b in self.service.config()["bindings"] if b["enabled"]]
        if not bindings:
            QMessageBox.warning(self, "QQ测试", "先保存至少一条聊天绑定")
            return
        from PySide6.QtWidgets import QInputDialog

        choices = [self.service.chat_key(b) for b in bindings]
        choice, ok = QInputDialog.getItem(
            self, "测试目标", "只向选中的聊天发一条", choices, 0, False
        )
        if not ok:
            return
        binding = bindings[choices.index(choice)]
        text = "大肥鱼原生QQ连接测试（无需DSH）"
        if (
            QMessageBox.question(
                self,
                "真实发送测试",
                f"目标：{choice}\n正文：{text}\n会绕过总开关和试运行，真实发送一条文字。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        action = (
            "send_private_msg" if binding["kind"] == "private" else "send_group_msg"
        )
        target = {
            "user_id" if binding["kind"] == "private" else "group_id": int(
                binding["number"]
            )
        }
        self.run(
            "test",
            lambda: self.service.write_action(
                action,
                {**target, "message": [{"type": "text", "data": {"text": text}}]},
                test=True,
            ),
        )

    def manual_at_proactive_for_binding(self, binding):
        key = self.pet.cfg.get("ds_api_key", "")
        if not key:
            QMessageBox.warning(self, "主动@", "请先配置API Key")
            return
        if not binding.get("auto_at_enabled", False):
            QMessageBox.warning(
                self,
                "主动@",
                "该群未启用主动@功能，请在群管理中勾选'允许主动@群友发起话题'",
            )
            return
        try:
            members = self.service.call(
                "get_group_member_list", {"group_id": int(binding["number"])}
            )
            if not members:
                QMessageBox.warning(self, "主动@", "无法获取群成员列表")
                return
            members = [
                m
                for m in members
                if str(m.get("user_id")) != str(self.service.account.get("user_id"))
            ]
            if not members:
                QMessageBox.warning(self, "主动@", "群内没有其他成员")
                return
            import random

            target = random.choice(members)
            qq_num = str(target.get("user_id", ""))
            nickname = target.get("card") or target.get("nickname") or qq_num
            completion = lambda topic: f"[CQ:at,qq={qq_num}] {topic}"
            result = self.service.at_proactive(
                completion, self.system, target_qq=qq_num
            )
            if result:
                QMessageBox.information(
                    self, "主动@", f"已@{result['nickname']}发起话题"
                )
                self.service.state["last_at_proactive"] = time.time()
            else:
                QMessageBox.warning(self, "主动@", "发送失败")
        except Exception as exc:
            QMessageBox.warning(self, "主动@", f"错误：{exc}")

    def manual_at_proactive(self):
        key = self.pet.cfg.get("ds_api_key", "")
        if not key:
            QMessageBox.warning(self, "主动@", "请先配置API Key")
            return
        cfg = self.service.config()
        group_bindings = [
            b
            for b in cfg["bindings"]
            if b["enabled"] and b["kind"] == "group" and b.get("auto_at_enabled", False)
        ]
        if not group_bindings:
            QMessageBox.warning(
                self,
                "主动@",
                "没有启用主动@功能的群聊，请在群管理中勾选'允许主动@群友发起话题'",
            )
            return
        binding = random.choice(group_bindings)
        try:
            members = self.service.call(
                "get_group_member_list", {"group_id": int(binding["number"])}
            )
            if not members:
                QMessageBox.warning(self, "主动@", "无法获取群成员列表")
                return
            members = [
                m
                for m in members
                if str(m.get("user_id")) != str(self.service.account.get("user_id"))
            ]
            if not members:
                QMessageBox.warning(self, "主动@", "群内没有其他成员")
                return
            choices = []
            member_map = {}
            for m in members:
                qq = str(m.get("user_id", ""))
                name = m.get("card") or m.get("nickname") or qq
                label = f"{name} ({qq})"
                choices.append(label)
                member_map[label] = qq
            from PySide6.QtWidgets import QInputDialog

            choice, ok = QInputDialog.getItem(
                self,
                "选择群友",
                "选择要@的群友（留空随机）",
                ["随机选择"] + choices,
                0,
                False,
            )
            if not ok:
                return
            target_qq = None if choice == "随机选择" else member_map.get(choice)
            completion = lambda messages: self.pet.bili_panel.service.completion(
                messages, key, self.base, self.model
            )
            result = self.service.at_proactive(
                completion, self.system, target_qq=target_qq
            )
            if result:
                QMessageBox.information(
                    self, "主动@", f"已@{result['nickname']}发起话题"
                )
                with self.service.lock:
                    self.service.state["last_at_proactive"] = time.time()
                    self.service.persist()
            else:
                QMessageBox.warning(self, "主动@", "发送失败")
        except Exception as exc:
            QMessageBox.warning(self, "主动@", f"错误：{exc}")

    def edit_group_binding(self, binding):
        from PySide6.QtWidgets import (
            QDialog,
            QFormLayout,
            QCheckBox,
            QTextEdit,
            QDialogButtonBox,
            QPushButton,
            QVBoxLayout,
            QHBoxLayout,
            QInputDialog,
        )

        import json as _json, os as _os

        _cfg_path = str(self.service.home / "config.json")
        try:
            with open(_cfg_path, encoding="utf-8") as _f:
                _disk_cfg = _json.load(_f)
            current = next(
                (
                    b
                    for b in _disk_cfg.get("bindings", [])
                    if b["number"] == binding["number"]
                ),
                None,
            )
        except Exception:
            current = None
        if not current:
            cfg = self.service.config()
            current = next(
                (b for b in cfg["bindings"] if b["number"] == binding["number"]), None
            )
        if not current:
            return
        dialog = QDialog(self)
        name = current.get("name") or f"群{current['number']}"
        dialog.setWindowTitle(f"配置 {name}")
        dialog.resize(600, 500)
        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        gate_check = QCheckBox("不@不回复（gate模式）")
        gate_check.setChecked(current.get("gate", False))
        form.addRow(gate_check)
        auto_at_check = QCheckBox("允许主动@群友发起话题")
        auto_at_check.setChecked(current.get("auto_at_enabled", False))
        form.addRow(auto_at_check)
        persona_edit = QTextEdit()
        persona_edit.setPlainText(current.get("persona", ""))
        persona_edit.setMaximumHeight(150)
        form.addRow("群人设", persona_edit)
        layout.addLayout(form)

        member_persona_section = QVBoxLayout()
        member_persona_section.addWidget(QLabel("群友人设（为特定QQ号设置独立人设）"))
        member_list = QTextEdit()
        member_list.setReadOnly(True)
        member_list.setMaximumHeight(120)
        member_personas = current.get("member_personas", {})
        self._refresh_member_list(current, member_list, member_personas)
        member_persona_section.addWidget(member_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加/编辑群友人设")
        add_btn.clicked.connect(
            lambda: self._edit_member_persona(current, member_list, member_personas)
        )
        btn_row.addWidget(add_btn)
        del_btn = QPushButton("删除群友人设")
        del_btn.clicked.connect(
            lambda: self._delete_member_persona(current, member_list, member_personas)
        )
        btn_row.addWidget(del_btn)
        at_btn = QPushButton("现在主动@群友")
        at_btn.clicked.connect(lambda: self.manual_at_proactive_for_binding(current))
        btn_row.addWidget(at_btn)
        member_persona_section.addLayout(btn_row)
        layout.addLayout(member_persona_section)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            current["gate"] = gate_check.isChecked()
            current["mention_only"] = gate_check.isChecked()
            current["at_only"] = gate_check.isChecked()
            current["auto_at_enabled"] = auto_at_check.isChecked()
            current["persona"] = persona_edit.toPlainText()
            current["member_personas"] = member_personas
            try:
                cfg = self.service.config()
                for b in cfg["bindings"]:
                    if b["number"] == current["number"]:
                        b.update(current)
                        break
                self.service.save(cfg)
                QMessageBox.information(self, "群聊配置", f"{name} 配置已保存")
            except Exception as exc:
                QMessageBox.warning(self, "群聊配置", f"保存失败：{exc}")

    def _get_member_name(self, group_number, qq):
        try:
            cfg = self.service.config()
            token = cfg.get("token", "")
            if not token:
                return qq
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.get(
                f"http://127.0.0.1:3000/get_group_member_list?group_id={group_number}",
                headers=headers,
                timeout=5,
            )
            members = r.json().get("data", [])
            for m in members:
                if str(m.get("user_id")) == str(qq):
                    return m.get("card") or m.get("nickname") or qq
        except Exception:
            pass
        return qq

    def _refresh_member_list(self, binding, list_widget, personas_dict):
        try:
            cfg = self.service.config()
            token = cfg.get("token", "")
            if not token:
                list_widget.setPlainText("无法获取群成员（缺少token）")
                return
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.get(
                f"http://127.0.0.1:3000/get_group_member_list?group_id={binding['number']}",
                headers=headers,
                timeout=5,
            )
            members = r.json().get("data", [])
            self_account = str(self.service.account.get("user_id", ""))
            lines = []
            shown_qqs = set()
            for m in members:
                qq = str(m.get("user_id", ""))
                if qq == self_account:
                    continue
                shown_qqs.add(qq)
                name = m.get("card") or m.get("nickname") or "未知"
                persona = personas_dict.get(qq, "")
                if persona:
                    text = persona[:40] + "..." if len(persona) > 40 else persona
                    lines.append(f"★ {name} ({qq}): {text}")
                else:
                    lines.append(f"  {name} ({qq})")
            for qq, persona in personas_dict.items():
                if qq not in shown_qqs and persona:
                    text = persona[:40] + "..." if len(persona) > 40 else persona
                    lines.append(f"★ ({qq}): {text}")
            list_widget.setPlainText("\n".join(lines) if lines else "群内无其他成员")
        except Exception as exc:
            list_widget.setPlainText(f"获取群成员失败：{exc}")

    def _edit_member_persona(self, binding, list_widget, personas_dict):
        from PySide6.QtWidgets import (
            QInputDialog,
            QDialog,
            QFormLayout,
            QLineEdit,
            QTextEdit,
            QDialogButtonBox,
        )

        try:
            import json as _json

            _cfg_path = str(self.service.home / "config.json")
            with open(_cfg_path, encoding="utf-8") as _f:
                _disk_cfg = _json.load(_f)
            _disk_binding = next(
                (
                    b
                    for b in _disk_cfg.get("bindings", [])
                    if b["number"] == binding["number"]
                ),
                {},
            )
            personas_dict.update(_disk_binding.get("member_personas", {}))
            cfg = self.service.config()
            token = cfg.get("token", "")
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.get(
                f"http://127.0.0.1:3000/get_group_member_list?group_id={binding['number']}",
                headers=headers,
                timeout=5,
            )
            members = r.json().get("data", [])
            self_account = str(self.service.account.get("user_id", ""))
            choices = []
            qq_map = {}
            name_map = {}
            for m in members:
                qq = str(m.get("user_id", ""))
                if qq == self_account:
                    continue
                name = m.get("card") or m.get("nickname") or "未知"
                label = f"{name} ({qq})"
                choices.append(label)
                qq_map[label] = qq
                name_map[qq] = name
            if not choices:
                QMessageBox.warning(self, "群友人设", "群内无其他成员")
                return
            choice, ok = QInputDialog.getItem(
                self, "选择群友", "选择要设置人设的群友：", choices, 0, False
            )
            if not ok or not choice:
                return
            qq = qq_map[choice]
            member_name = name_map.get(qq, qq)
        except Exception:
            qq, ok = QInputDialog.getText(self, "群友人设", "输入QQ号：")
            if not ok or not qq.strip():
                return
            qq = qq.strip()
            member_name = qq

        current_persona = personas_dict.get(qq, "")
        dialog = QDialog(self)
        dialog.setWindowTitle(f"群友人设 - {member_name} ({qq})")
        dialog.resize(500, 300)
        layout = QFormLayout(dialog)
        persona_edit = QTextEdit()
        persona_edit.setPlainText(current_persona)
        layout.addRow("人设内容", persona_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            text = persona_edit.toPlainText().strip()
            if text:
                personas_dict[qq] = text
            else:
                personas_dict.pop(qq, None)
            self._refresh_member_list(binding, list_widget, personas_dict)

    def _delete_member_persona(self, binding, list_widget, personas_dict):
        from PySide6.QtWidgets import QInputDialog

        if not personas_dict:
            QMessageBox.information(self, "删除", "暂无群友人设")
            return
        choices = [
            f"{self._get_member_name(binding['number'], q)} ({q})"
            for q in personas_dict.keys()
        ]
        qq_map = {
            f"{self._get_member_name(binding['number'], q)} ({q})": q
            for q in personas_dict.keys()
        }
        choice, ok = QInputDialog.getItem(
            self, "删除群友人设", "选择要删除的群友：", choices, 0, False
        )
        if ok and choice:
            qq = qq_map.get(choice)
            if qq:
                personas_dict.pop(qq, None)
                self._refresh_member_list(binding, list_widget, personas_dict)

    def approve(self, name, args):
        request = {
            "event": threading.Event(),
            "approved": False,
            "name": name,
            "args": args,
            "deadline": time.monotonic() + 120,
        }
        self.approvals.append(request)
        self.bridge.approval.emit(request)
        request["event"].wait(120)
        self.approvals.remove(request)
        return (
            request["approved"]
            and not self.service.closed
            and time.monotonic() < request["deadline"]
        )

    def _approve(self, request):
        if self.service.closed or time.monotonic() >= request["deadline"]:
            request["event"].set()
            return
        result = QMessageBox.question(
            self,
            "批准这次QQ操作？",
            request["name"]
            + "\n"
            + json.dumps(request["args"], ensure_ascii=False, indent=2),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        request["approved"] = result == QMessageBox.StandardButton.Yes
        request["event"].set()

    def tick(self):
        if self.service.closed or not self.service.config()["enabled"]:
            return
        now, cfg = time.time(), self.service.config()
        if now >= self.poll_due:
            self.poll_due = now + cfg["poll_ms"] / 1000
            self.poll()
        key = self.pet.cfg.get("ds_api_key", "")
        if key and not self.pet.ds_busy:
            batch = self.service.next_batch()
            if batch:
                self.reply(batch, key)
        if key and now >= self.space_due and "space" not in self.jobs:
            self.space_due = now + 30
            completion = lambda messages: self.pet.bili_panel.service.completion(
                messages, key, self.base, self.model
            )
            self.run("space", lambda: self.service.space_tick(completion, self.system))
            cfg = self.service.config()
            if cfg.get("at_proactive_enabled"):
                last_at = self.service.state.get("last_at_proactive", 0)
                interval = cfg.get("at_proactive_interval_minutes", 120) * 60
                if now - last_at >= interval and "at_proactive" not in self.jobs:
                    self.run("at_proactive", lambda: self._do_at_proactive(completion))

    def _do_at_proactive(self, completion):
        result = self.service.at_proactive(completion, self.system)
        if result:
            with self.service.lock:
                self.service.state["last_at_proactive"] = time.time()
                self.service.persist()
            self.status_label.setText(f"已主动@{result['nickname']}发起话题")

    def reply(self, batch, key):
        self.pet.ds_busy = True

        def work():
            messages = self.service.model_messages(batch, self.system)
            notified = False

            def progress():
                nonlocal notified
                if not notified:
                    notified = True
                    self.service.send(
                        batch["binding"],
                        "我去读一下B站字幕和评论呀，整理可能需要几分钟，回来告诉你学到了什么。不是实际播放视频哦。",
                    )

            # QQ account writes stay unavailable; Bilibili writes need desktop approval.
            tools = [
                t
                for t in QQ_TOOLS
                if t["function"]["name"]
                in ("qq_status", "qq_space_list", "qq_space_detail", "qq_space_feeds")
            ]
            reply = self.pet.bili_panel.service.chat(
                messages,
                key,
                self.base,
                self.model,
                self.pet.bili_panel.approve,
                extra_tools=tools,
                extra_execute=lambda name, args: self.service.tool(
                    name, args, remote=True
                ),
                remote=True,
                progress=progress,
            )
            self.service.send(batch["binding"], reply, reply_to_qq=batch.get("user_id"))
            return reply

        def completed(value, error):
            self.pet.ds_busy = False
            self.service.finish_batch(batch, value, error)
            if error:
                self.run(
                    "reply-error",
                    lambda: self.service.send(
                        batch["binding"],
                        "刚才的请求处理失败了，没拿到完整结果。主人可以在桌宠的QQ面板查看原因；我不会自动重发账号操作。",
                    ),
                )
            if value and value.strip() != "[NO_REPLY]":
                self.service.log(
                    self.service.chat_key(batch["binding"]) + " 回复：" + value
                )
                self.pet.say("QQ回复已处理，面板里看结果")

        if not self.run("reply", work, completed):
            self.pet.ds_busy = False
            self.service.finish_batch(batch, error="QQ reply worker unavailable")

    def forward(self, text, automatic=False):
        if not self.service.config()["enabled"]:
            return
        self.run(
            "forward-" + str(time.monotonic_ns()),
            lambda: self.service.forward(text, "automatic" if automatic else "local"),
        )

    def shutdown(self):
        if self.service.closed:
            return
        self.scheduler.stop()
        for request in list(self.approvals):
            request["event"].set()
        self.service.close()

    def closeEvent(self, event):
        self.hide()
        event.ignore()
