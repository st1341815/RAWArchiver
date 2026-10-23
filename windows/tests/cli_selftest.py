#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 版 CLI 自测：验证 frozen 环境 + 动态 import core + ExifTool 链路。

用 Python 原生 tempfile（避免 git-bash 的 /tmp 路径 Windows Python 不认）。
输出全 ASCII（Windows 控制台默认 cp1252，避免编码崩）。
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.normpath(os.path.join(HERE, "..", "dist", "RawArchiver"))
CLI = os.path.join(DIST, "RawArchiver-cli.exe")


def run(args, timeout=300):
    return subprocess.check_output(
        [CLI] + args, text=True, encoding="utf-8", errors="replace",
        timeout=timeout)


def main():
    from PIL import Image  # noqa: F401

    assert os.path.isfile(CLI), "missing %s" % CLI

    # 1) doctor
    doc = run(["--doctor"])
    print("doctor: %s" % doc.strip())
    d = json.loads(doc)
    assert d["exifread"], "exifread not bundled"
    assert d["pillow"], "Pillow not bundled"
    p = d.get("exiftool") or ""
    assert p and "exiftool" in p.lower(), "ExifTool not bundled: %s" % p
    cands = [p, p + ".exe"]
    assert any(os.path.exists(c) for c in cands), "ExifTool file missing: %s" % p
    print("OK: exifread / Pillow / ExifTool all available")

    # 2) preview
    t = tempfile.mkdtemp(prefix="rawcli-")
    Image.new("RGB", (8, 6), (200, 120, 40)).save(os.path.join(t, "a.jpg"), quality=85)
    r = json.loads(run([t, "--output", os.path.join(t, "out"), "--preview"]))
    assert r["total"] == 1, "preview expected 1 file, got %s" % r["total"]
    print("OK: CLI forwarding + preview pipeline (1 file)")

    print("SELFTEST_CLI_OK")


if __name__ == "__main__":
    main()
