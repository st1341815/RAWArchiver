#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAW 归档 macOS 版 —— 本地自测（平台无关部分，Linux/macOS 都能跑）。

覆盖：静态页 / token 鉴权 / info / doctor / browse / preview / start / status /
      cancel / cleanup，以及「任务态写 TRIM_PKGVAR、日志写 <输出目录>/log/」的盘面约定。
用法：python3 macos/tests/selftest_server.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(os.path.dirname(HERE), "app")   # macos/app
SERVER = os.path.join(APP, "server_mac.py")
PY = sys.executable

PASS = []


def ok(name, cond, detail=""):
    if not cond:
        print("FAIL: %s %s" % (name, detail))
        sys.exit(1)
    PASS.append(name)
    print("  ok: %s" % name)


def call(url, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def jcall(url, data=None):
    st, txt = call(url, data)
    return st, json.loads(txt)


def main():
    from PIL import Image  # noqa: F401  （测试依赖）

    tmp = tempfile.mkdtemp(prefix="ra-mac-test-")
    var = os.path.join(tmp, "var")
    src = os.path.join(tmp, "src")
    out = os.path.join(tmp, "out")
    os.makedirs(var)
    os.makedirs(src)

    # 造两张带 EXIF 的测试图（拍摄日期 2024-05-06，品牌 Canon）
    ex = Image.Exif()
    ex[36867] = "2024:05:06 07:08:09"   # DateTimeOriginal
    ex[271] = "Canon"                   # Make
    for name in ("a.jpg", "b.jpg"):
        Image.new("RGB", (16, 12), (10, 100, 200)).save(
            os.path.join(src, name), exif=ex.tobytes())

    env = dict(os.environ, TRIM_PKGVAR=var, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([PY, SERVER], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    try:
        line = proc.stdout.readline().strip()
        m = re.search(r"http\S+", line)
        ok("server 启动并打印 URL", bool(m), line)
        url = m.group(0)
        root = url.split("/app/rawarchiver/")[0]
        base = re.search(r"(http://127\.0\.0\.1:\d+)", url).group(1)
        token = url.split("t=")[1]
        api = base + "/app/rawarchiver/api"

        # ---- 静态页 ----
        st, txt = call(base + "/app/rawarchiver/")
        ok("静态页 200", st == 200 and "RAW 归档" in txt, st)
        st, _ = call(base + "/app/rawarchiver/auth-callback.html")
        ok("auth-callback 静态页可访问", st == 200, st)

        # ---- token 鉴权 ----
        st, _ = call(api + "?action=info")
        ok("无 token => 403", st == 403, st)
        st, d = jcall(api + "?action=info&t=" + token)
        ok("info 带 token 200", st == 200 and d.get("ok"), d)
        ok("mode=macos", d.get("mode") == "macos", d.get("mode"))
        ok("version 非空", bool(d.get("version")), d.get("version"))

        # ---- doctor ----
        st, d = jcall(api + "?action=doctor&t=" + token)
        ok("doctor 可执行", st == 200 and d.get("ok"), d)
        dr = d.get("result", {})
        ok("doctor 报告 exifread", dr.get("exifread") is True, dr)
        ok("doctor 报告 pillow", dr.get("pillow") is True, dr)
        print("    (exiftool: %s)" % dr.get("exiftool"))

        # ---- browse ----
        st, d = jcall(api + "?action=browse&t=" + token, {"path": tmp})
        ok("browse 列出目录", st == 200 and d.get("ok") and
           any(x["name"] == "src" for x in d.get("dirs", [])), d)

        # ---- preview ----
        st, d = jcall(api + "?action=preview&t=" + token,
                      {"source": src, "output": out})
        res = d.get("result", {})
        ok("preview ok", st == 200 and d.get("ok"), d)
        ok("preview total=2", res.get("total") == 2, res.get("total"))
        ok("preview 读到拍摄日期", res.get("date_range") == ["2024-05-06", "2024-05-06"],
           res.get("date_range"))
        ok("preview 目标名含日期", all("20240506" in (r.get("dst_rel") or "")
                                   for r in res.get("sample", [])), res.get("sample"))

        # ---- start / status ----
        st, d = jcall(api + "?action=start&t=" + token,
                      {"source": src, "output": out, "mode": "copy",
                       "staging": False, "taskId": "selftest001"})
        ok("start 返回 taskId", d.get("ok") and d.get("taskId") == "selftest001", d)
        state = None
        for _ in range(120):
            st, d = jcall(api + "?action=status&t=" + token,
                          {"id": "selftest001", "output": out})
            if d.get("ok") and d.get("state", {}).get("status") in (
                    "done", "error", "cancelled"):
                state = d["state"]
                break
            time.sleep(0.5)
        ok("任务完成", state and state.get("status") == "done",
           state and state.get("status"))
        ok("成功数=2", state and state.get("success") == 2, state and state.get("success"))
        dst = os.path.join(out, "20240506", "a_20240506.jpg")
        ok("归档落盘 20240506/a_20240506.jpg", os.path.isfile(dst), dst)
        ok("源文件保留（copy 模式）", os.path.isfile(os.path.join(src, "a.jpg")))
        ok("日志写在 <输出>/log/", os.path.isfile(
            os.path.join(out, "log", "rawarchiver_selftest001.log")))
        ok("报告写在 <输出>/log/", os.path.isfile(
            os.path.join(out, "log", "_report_selftest001.json")))
        ok("任务态写在 TRIM_PKGVAR", os.path.isfile(os.path.join(
            var, ".rawarchiver", "tasks", "selftest001", "state.json")))
        ok("输出目录根部无 .rawarchiver", not os.path.exists(os.path.join(out, ".rawarchiver")))
        ok("源目录零新增", sorted(os.listdir(src)) == ["a.jpg", "b.jpg"], os.listdir(src))

        # ---- 未知动作 ----
        st, d = jcall(api + "?action=nope&t=" + token)
        ok("未知动作报错", d.get("ok") is False)

        # ---- cancel（造一批文件，尽快取消）----
        src2 = os.path.join(tmp, "src2")
        os.makedirs(src2)
        for i in range(40):
            Image.new("RGB", (64, 48), (i, 50, 80)).save(
                os.path.join(src2, "%03d.jpg" % i), exif=ex.tobytes())
        st, d = jcall(api + "?action=start&t=" + token,
                      {"source": src2, "output": os.path.join(tmp, "out2"),
                       "mode": "copy", "staging": False, "taskId": "selftest002"})
        ok("start#2", d.get("ok"), d)
        time.sleep(0.3)
        st, d = jcall(api + "?action=cancel&t=" + token, {"taskId": "selftest002"})
        ok("cancel 接口 ok", d.get("ok"), d)
        stt = None
        for _ in range(120):
            st, d = jcall(api + "?action=status&t=" + token,
                          {"id": "selftest002", "output": os.path.join(tmp, "out2")})
            if d.get("ok") and d.get("state", {}).get("status") in (
                    "done", "error", "cancelled"):
                stt = d["state"]["status"]
                break
            time.sleep(0.5)
        ok("cancel 后任务终止", stt in ("cancelled", "done"), stt)

        # ---- cleanup（copy 模式下无 to_delete，应 ok 或明确错误）----
        st, d = jcall(api + "?action=cleanup&t=" + token,
                      {"taskId": "selftest001", "output": out})
        ok("cleanup 接口响应", st == 200 and "ok" in d, d)

        print("\nSELFTEST_MAC_OK (%d 项)" % len(PASS))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
