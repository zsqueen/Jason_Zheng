# -*- coding: utf-8 -*-
"""打源码分享 zip（排除 venv/打包产物/配置）"""

import os
import zipfile
from pathlib import Path

BASE = str(Path(__file__).resolve().parent)
OUT = str(Path(BASE).parent / "大肥鱼桌宠_源码.zip")

files = [
    "桌宠.py",
    "preprocess.py",
    "preprocess2.py",
    "启动桌宠.bat",
    "requirements.txt",
    "README.md",
    "LICENSE",
    "icon.ico",
    ".gitignore",
]
for directory in ("sprites", "qq", "bili"):
    for root, dirs, fs in os.walk(os.path.join(BASE, directory)):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in fs:
            if directory != "sprites" and not f.endswith(".py"):
                continue
            files.append(
                os.path.relpath(os.path.join(root, f), BASE).replace(os.sep, "/")
            )

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(os.path.join(BASE, f), f)

print("files:", len(files))
print("size:", os.path.getsize(OUT) // 1024, "KB")
for f in files:
    print(" ", f)
