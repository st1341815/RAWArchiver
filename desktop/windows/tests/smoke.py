#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 原生版（WPF）smoke test：验证 exe 结构 + 内嵌 CLI 的 IPC 全链路。

用 Python tempfile（避免 git-bash 的 /tmp 路径 Windows 原生 Python 不认）。
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLISH = os.path.normpath(os.path.join(HERE, "..", "dist", "publish"))
EXE = os.path.join(PUBLISH, "RawArchiver.exe")
INNER = os.path.join(PUBLISH, "RawArchiver-cli", "RawArchiver-cli.exe")


def main():
    from PIL import Image  # noqa: F401

    assert os.path.isfile(EXE), "missing WPF exe: %s" % EXE
    print("wpf exe OK")

    # 1) doctor
    doc = subprocess.check_output([INNER, "--doctor"], encoding="utf-8", errors="replace")
    d = json.loads(doc)
    assert d["exifread"] and d["pillow"] and d["exiftool"], d
    print("cli doctor OK: exiftool=%s" % d["exiftool"])

    # 2) IPC preview 全链路
    t = tempfile.mkdtemp(prefix="rawcli-")
    Image.new("RGB", (8, 6), (200, 120, 40)).save(os.path.join(t, "a.jpg"), quality=85)
    p = subprocess.Popen([INNER, "--ipc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, encoding="utf-8")
    p.stdin.write(json.dumps({"id": 1, "cmd": "preview", "source": t,
                              "output": os.path.join(t, "out"), "opts": {}}) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    r = json.loads(line)
    assert r.get("id") == 1 and r["result"]["total"] == 1, r
    print("ipc preview OK")
    p.terminate()

    print("SELFTEST_WIN_SMOKE_OK")


if __name__ == "__main__":
    main()
