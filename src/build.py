# -*- coding: utf-8 -*-
"""Build MikagePromptTable.exe into the project root.
Run:  python src/build.py
"""
import os
import subprocess
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)                      # repo root
DIST = os.path.join(ROOT, "dist")                # build output goes to dist/
WORK = os.path.join(ROOT, "build", "work")

PY = sys.executable
COMMON = [
    "--onefile", "--noconsole", "--clean",
    "--distpath", DIST, "--workpath", WORK, "--specpath", SRC,
    "--collect-all", "webview",
    "--collect-all", "pythonnet",
    "--hidden-import", "openpyxl",
    "--hidden-import", "PIL",
    "--hidden-import", "numpy",
]


def build(name, entry, icon, extra_data):
    cmd = [PY, "-m", "PyInstaller", "--name", name] + COMMON + [
        "--icon", icon, "--add-data", extra_data, entry,
    ]
    print(f"\n=== Building {name}.exe ===")
    res = subprocess.run(cmd, cwd=SRC)
    if res.returncode != 0:
        sys.exit(res.returncode)
    exe = os.path.join(DIST, f"{name}.exe")
    print(f"Done: {exe} ({os.path.getsize(exe) / 1024 / 1024:.1f} MB)")


def main():
    icon = os.path.join(SRC, "assets", "app.ico")

    build("MikagePromptTable",
          os.path.join(SRC, "app.py"),
          icon,
          os.path.join(SRC, "web") + ";web")
    print("\nExecutable is in", DIST)


if __name__ == "__main__":
    main()
