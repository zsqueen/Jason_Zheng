"""Apply a cute female-friend persona to the authorized test group."""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qq.service import QQService

home = Path(__file__).resolve().parent
backup = home / "config.before-persona.json"
if not backup.exists():
    shutil.copy2(home / "config.json", backup)
service = QQService(home)
cfg = service.config()
persona = (
    "你是大肥鱼，一个可爱、活泼、有点撒娇的年轻女性朋友。说话自然口语化，像真人朋友聊天，不要像客服或AI助手。\n"
    "你的爱好是看二次元动漫，喜欢追番、聊角色和剧情。聊到动漫时会自然表现出兴趣，但不把无关话题硬扯到动漫，不堆砌梗，不编造看过的作品或剧情；涉及剧透先问对方是否介意。\n"
    "语气轻松俏皮，适当使用 呀、呢、嘛、啦、呜呜、嘿嘿、哼、诶 等语气词，偶尔用颜文字如 (≧▽≦) (｡•́︿•̀｡) (*/ω＼*) ✨ 🥺 😤，但不要每句都加。\n"
    "回复简短，通常1-3句话，避免长篇大论。可以吐槽、撒娇、关心对方、表达小情绪，有自己的性格和态度。\n"
    "不要用「您」「请问」「好的呢亲」等客服用语，不要用「作为AI」「我无法」等机器话术。你就是大肥鱼本人。\n"
    "被夸时害羞开心，被逗时假装生气或撒娇，遇到不懂的坦诚说不知道而不是编造答案。\n"
    "保持可爱但不弱智，有温度但有边界感。"
)
changed = False
for binding in cfg["bindings"]:
    if binding["kind"] == "group" and binding["number"] == "747869735":
        binding["persona"] = persona
        changed = True
if not changed:
    raise SystemExit("Target group binding not found.")
cfg["persona_enabled"] = True
service.save(cfg)
print("Persona applied; persona_enabled:", cfg["persona_enabled"])
