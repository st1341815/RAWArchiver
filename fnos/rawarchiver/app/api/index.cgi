#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAW 归档 —— fnOS JSON API（CGI）。

请求：POST，body 为 JSON {"action": ..., ...}（action 也可放在 query 上）。
响应：Content-Type: application/json，body 为单个 JSON。

动作：info / doctor / devices / browse / mkdir / preview / start / status / cancel / cleanup / rollback
说明：所有实际归档逻辑都在随包核心脚本 scripts/raw_archiver.py（只用标准库）；
     本 API 只做参数转发与状态读取。照片无 EXIF 视为未知并跳过，视频可用文件时间兜底。
"""

import os
import sys
import json
import random
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs

APP_NAME = "rawarchiver"
SELF = os.path.abspath(__file__)
APP_DEST = os.path.dirname(os.path.dirname(SELF))          # .../target
SCRIPT = os.path.join(APP_DEST, "scripts", "raw_archiver.py")
APP_VAR = os.environ.get("TRIM_PKGVAR") or "/var/apps/%s/var" % APP_NAME


def pybin():
    p = os.path.join(APP_VAR, "python_path")
    if os.path.isfile(p):
        try:
            v = open(p, encoding="utf-8").read().strip()
            if v and os.path.exists(v):
                return v
        except Exception:
            pass
    v = os.path.join(APP_VAR, "venv", "bin", "python3")
    if os.path.exists(v):
        return v
    return sys.executable or "python3"


def call(*args, timeout=1800):
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.check_output(
        [pybin(), "-X", "utf8", SCRIPT, *[str(a) for a in args]],
        text=True, timeout=timeout, env=env, cwd=APP_DEST)


def emit(obj):
    sys.stdout.write("Content-Type: application/json; charset=utf-8\n\n")
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def read_body():
    n = os.environ.get("CONTENT_LENGTH") or ""
    try:
        if n.isdigit() and int(n) > 0:
            return sys.stdin.read(int(n))
        return sys.stdin.read()
    except Exception:
        return ""


def optargs(b):
    a = []
    if b.get("brandFolder"):
        a.append("--brand")
    if b.get("handleJpg") is False:
        a.append("--no-jpg")
    if b.get("handleVideo") is False:
        a.append("--no-video")
    if b.get("monthDir"):
        a.append("--month")
    a.append("--staging" if b.get("staging", True) else "--no-staging")
    return a


def list_devices():
    out = []

    def count_jpg(root):
        try:
            return sum(1 for _ in Path(root).rglob("*.JPG")) + sum(1 for _ in Path(root).rglob("*.jpg"))
        except Exception:
            return 0

    for pat in ("volumeUSB*/usbshare*", "volumeUSB*/usbshare", "media/*/*", "run/media/*/*", "mnt/usb*"):
        try:
            for d in sorted(Path("/").glob(pat)):
                if d.is_dir():
                    out.append({"path": str(d), "label": d.name, "files": count_jpg(d)})
        except Exception:
            pass
    return out


def browse_dirs(path):
    """列出目录下的一级子目录，供前端「选取文件夹」弹窗导航。

    只返回目录、跳过隐藏项（点号开头）。parent 为 None 表示已到根目录；
    writable 供前端提示当前目录是否可写。
    """
    try:
        p = Path(os.path.abspath((path or "").strip() or "/"))
        if not p.is_dir():
            return {"ok": False, "error": "不是目录: %s" % p}
        dirs = []
        try:
            entries = sorted(p.iterdir(), key=lambda c: c.name.lower())
        except OSError as e:
            return {"ok": False, "error": "无法读取目录: %s" % e}
        for c in entries:
            if c.name.startswith("."):
                continue
            try:
                if c.is_dir():
                    dirs.append({"name": c.name, "path": str(c)})
            except OSError:
                continue
        parent = str(p.parent) if str(p) != p.anchor else None
        return {"ok": True, "path": str(p), "parent": parent,
                "writable": os.access(str(p), os.W_OK), "dirs": dirs}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def main():
    body = read_body()
    b = {}
    if body and body.strip():
        try:
            b = json.loads(body)
        except Exception:
            b = {}
    if not isinstance(b, dict):
        b = {}
    q = parse_qs(os.environ.get("QUERY_STRING", ""))
    act = b.get("action") or (q.get("action", [""])[0]) or "info"
    out = (b.get("output") or "").strip()

    if act == "info":
        emit({"ok": True, "app": "RAW 归档", "version": "1.0.11", "mode": "fnos-cgi",
              "script": SCRIPT, "python": pybin()})
    elif act == "doctor":
        emit({"ok": True, "result": json.loads(call("--doctor"))})
    elif act == "devices":
        emit({"ok": True, "list": list_devices()})
    elif act == "browse":
        emit(browse_dirs(b.get("path", "")))
    elif act == "mkdir":
        p = b.get("path", "")
        if not p:
            emit({"ok": False, "error": "path 必填"})
        else:
            Path(p).mkdir(parents=True, exist_ok=True)
            emit({"ok": True, "path": p})
    elif act == "preview":
        if not b.get("source"):
            emit({"ok": False, "error": "source 必填"})
        else:
            emit({"ok": True, "result": json.loads(
                call(b["source"], "--output", out or ".", "--preview", *optargs(b)))})
    elif act == "start":
        if not (b.get("source") and out):
            emit({"ok": False, "error": "source 与 output 必填"})
        else:
            tid = b.get("taskId") or "%s_%d" % (time.strftime("%Y%m%d_%H%M%S"), random.randint(1000, 9999))
            args = [b["source"], "--output", out, "--mode", b.get("mode", "copy"),
                    "--task-id", tid, *optargs(b)]
            logdir = Path(out) / ".rawarchiver" / "tasks" / tid
            logdir.mkdir(parents=True, exist_ok=True)
            lf = open(logdir / "run.log", "a", encoding="utf-8")
            subprocess.Popen([pybin(), "-X", "utf8", SCRIPT, *[str(a) for a in args]],
                             stdout=lf, stderr=subprocess.STDOUT, cwd=APP_DEST)
            emit({"ok": True, "taskId": tid})
    elif act == "status":
        p = Path(out) / ".rawarchiver" / "tasks" / b.get("id", "") / "state.json"
        if not p.exists():
            emit({"ok": False, "error": "任务不存在"})
        else:
            st = json.loads(p.read_text(encoding="utf-8"))
            st["logs"] = st.get("logs", [])[-80:]
            st.pop("done", None)
            st.pop("to_delete", None)
            emit({"ok": True, "state": st})
    elif act == "cancel":
        d = Path(out) / ".rawarchiver" / "tasks" / b.get("taskId", "")
        if not d.is_dir():
            emit({"ok": False, "error": "任务不存在"})
        else:
            (d / "cancel").write_text("1", encoding="utf-8")
            emit({"ok": True})
    elif act == "cleanup":
        emit({"ok": True, **json.loads(call("--output", out, "--task-id", b.get("taskId", ""), "--cleanup"))})
    elif act == "rollback":
        emit({"ok": True, **json.loads(call("--output", out, "--task-id", b.get("taskId", ""), "--rollback"))})
    else:
        emit({"ok": False, "error": "未知动作: %s" % act})


if __name__ == "__main__":
    main()
