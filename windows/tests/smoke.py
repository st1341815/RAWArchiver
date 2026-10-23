#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 版 smoke test：起 GUI（RawArchiver.exe --gui）→ 验证本地 HTTP 服务 + API 全链路。

在 CI 的 windows runner 上跑（用 .venv 的 python，Pillow 在 venv 里）。
验证：gui.url 落盘 → 静态页 → info(mode=windows) → token 鉴权 → preview（frozen worker）。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.normpath(os.path.join(HERE, "..", "dist", "RawArchiver"))
BIN = os.path.join(DIST, "RawArchiver.exe")
VAR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "RawArchiver")
URLFILE = os.path.join(VAR, "gui.url")


def main():
    from PIL import Image  # noqa: F401（测试依赖，venv 里有）

    if not os.path.isfile(BIN):
        print("FAIL: not found %s" % BIN)
        sys.exit(1)

    if os.path.exists(URLFILE):
        os.remove(URLFILE)

    proc = subprocess.Popen([BIN, "--gui"])
    url = None
    try:
        for _ in range(40):
            if os.path.exists(URLFILE):
                with open(URLFILE, encoding="utf-8") as f:
                    url = f.read().strip()
                break
            time.sleep(1)
        assert url, "gui.url not found (GUI server not started)"
        print("gui url: %s" % url)

        token = url.split("t=")[1]
        origin = url.split("/app/rawarchiver/")[0]
        api = origin + "/app/rawarchiver/api"

        # 1) static
        with urllib.request.urlopen(url, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
        assert "RAW 归档" in html, "static page missing title"
        print("static OK")

        # 2) info（mode 应为 windows）
        with urllib.request.urlopen(api + "?action=info&t=" + token, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        assert d.get("ok") and d.get("mode") == "windows", d
        print("info/mode=windows OK")

        # 3) token 鉴权：无 token 应 403
        try:
            urllib.request.urlopen(api + "?action=info", timeout=30)
            raise AssertionError("no token should be rejected")
        except urllib.error.HTTPError as e:
            assert e.code == 403, "expect 403, got %s" % e.code
        print("token 403 OK")

        # 4) preview（frozen cli worker → core → JSON）
        tmp = tempfile.mkdtemp(prefix="rawin-")
        from PIL import Image
        Image.new("RGB", (8, 6), (200, 120, 40)).save(
            os.path.join(tmp, "a.jpg"), quality=85)
        body = json.dumps({"action": "preview", "source": tmp, "output": os.path.join(tmp, "out")}).encode()
        req = urllib.request.Request(
            api + "?action=preview&t=" + token, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode("utf-8"))
        assert d.get("ok") and d.get("result", {}).get("total") == 1, d
        print("preview OK")

        print("SELFTEST_WINDOWS_OK")
    finally:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


if __name__ == "__main__":
    main()
