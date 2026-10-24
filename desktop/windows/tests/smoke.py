#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 原生版（WPF，单文件 exe）smoke test。

验证：
  1. dist/publish 只有 1 个文件（RawArchiver.exe，真正的单文件）
  2. 内嵌上游的 onefile CLI 的 doctor（exifread/Pillow/ExifTool）
  3. 该 CLI 的 IPC preview 全链路
用 Python tempfile（避免 git-bash /tmp 路径 Windows 原生 Python 不认）。
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.normpath(os.path.join(HERE, "..", "dist"))
PUBLISH = os.path.join(DIST, "publish")
EXE = os.path.join(PUBLISH, "RawArchiver.exe")
CLI = os.path.join(DIST, "onefile", "RawArchiver-cli.exe")


def main():
    from PIL import Image  # noqa: F401

    # 1) 单文件校验
    files = os.listdir(PUBLISH)
    assert len(files) == 1 and files[0].lower() == "rawarchiver.exe", \
        "publish 目录不是单文件: %s" % files
    assert os.path.getsize(EXE) > 20 * 1024 * 1024, "exe 体积异常"
    print("single-file exe OK: %s (%.1f MB)" % (files[0], os.path.getsize(EXE) / 1048576))

    # 2) CLI doctor
    assert os.path.isfile(CLI), "missing CLI: %s" % CLI
    doc = subprocess.check_output([CLI, "--doctor"], encoding="utf-8", errors="replace")
    d = json.loads(doc)
    assert d["exifread"] and d["pillow"] and d["exiftool"], d
    print("cli doctor OK: exiftool=%s" % d["exiftool"])

    # 3) IPC preview
    t = tempfile.mkdtemp(prefix="rawcli-")
    Image.new("RGB", (8, 6), (200, 120, 40)).save(os.path.join(t, "a.jpg"), quality=85)
    p = subprocess.Popen([CLI, "--ipc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, encoding="utf-8")
    p.stdin.write(json.dumps({"id": 1, "cmd": "preview", "source": t,
                              "output": os.path.join(t, "out"), "opts": {}}) + "\n")
    p.stdin.flush()
    r = json.loads(p.stdout.readline())
    assert r.get("id") == 1 and r["result"]["total"] == 1, r
    print("ipc preview OK")
    p.terminate()

    print("SELFTEST_WIN_SMOKE_OK")


if __name__ == "__main__":
    main()
