#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAW 归档 —— fnOS 统一网关常驻服务。

监听 Unix Socket（TRIM_APPDEST/rawarchiver.sock），提供：
  - 静态文件（www/）
  - JSON API（复用原 api/index.cgi 的动作：info/doctor/devices/browse/mkdir/preview/start/status/cancel/cleanup/rollback）

网关转发请求路径形如 /app/rawarchiver/...，本服务会剥离前缀后映射到 www/ 或 /api。
所有实际归档逻辑仍在 scripts/raw_archiver.py（只用标准库），本服务只做参数转发与状态读取。
"""

import os
import sys
import json
import random
import subprocess
import socketserver
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_NAME = "rawarchiver"
GATEWAY_PREFIX = "/app/" + APP_NAME

SELF = os.path.abspath(__file__)
# 本脚本在打包后位于 target 根目录（app/server.py -> .../target/server.py）
APP_DEST = os.path.dirname(SELF)
SCRIPT = os.path.join(APP_DEST, "scripts", "raw_archiver.py")
WWW = os.path.join(APP_DEST, "www")
APP_VAR = os.environ.get("TRIM_PKGVAR") or "/var/apps/%s/var" % APP_NAME
SOCK_PATH = os.path.join(APP_DEST, "rawarchiver.sock")

VERSION = "1.0.13"


def log(msg):
    try:
        with open(os.path.join(APP_VAR, "gateway.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


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
            return (sum(1 for _ in Path(root).rglob("*.JPG"))
                    + sum(1 for _ in Path(root).rglob("*.jpg")))
        except Exception:
            return 0

    for pat in ("volumeUSB*/usbshare*", "volumeUSB*/usbshare", "media/*/*",
                "run/media/*/*", "mnt/usb*"):
        try:
            for d in sorted(Path("/").glob(pat)):
                if d.is_dir():
                    out.append({"path": str(d), "label": d.name, "files": count_jpg(d)})
        except Exception:
            pass
    return out


def browse_dirs(path):
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


def handle_action(b, q):
    act = b.get("action") or (q.get("action", [""])[0]) or "info"
    out = (b.get("output") or "").strip()

    if act == "info":
        return {"ok": True, "app": "RAW 归档", "version": VERSION, "mode": "fnos-gateway",
                "script": SCRIPT, "python": pybin()}
    if act == "doctor":
        return {"ok": True, "result": json.loads(call("--doctor"))}
    if act == "devices":
        return {"ok": True, "list": list_devices()}
    if act == "browse":
        return browse_dirs(b.get("path", ""))
    if act == "mkdir":
        p = b.get("path", "")
        if not p:
            return {"ok": False, "error": "path 必填"}
        Path(p).mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": p}
    if act == "preview":
        if not b.get("source"):
            return {"ok": False, "error": "source 必填"}
        return {"ok": True, "result": json.loads(
            call(b["source"], "--output", out or ".", "--preview", *optargs(b)))}
    if act == "start":
        if not (b.get("source") and out):
            return {"ok": False, "error": "source 与 output 必填"}
        tid = b.get("taskId") or "%s_%d" % (time.strftime("%Y%m%d_%H%M%S"), random.randint(1000, 9999))
        args = [b["source"], "--output", out, "--mode", b.get("mode", "copy"),
                "--task-id", tid, *optargs(b)]
        logdir = Path(out) / ".rawarchiver" / "tasks" / tid
        logdir.mkdir(parents=True, exist_ok=True)
        lf = open(logdir / "run.log", "a", encoding="utf-8")
        subprocess.Popen([pybin(), "-X", "utf8", SCRIPT, *[str(a) for a in args]],
                         stdout=lf, stderr=subprocess.STDOUT, cwd=APP_DEST)
        return {"ok": True, "taskId": tid}
    if act == "status":
        p = Path(out) / ".rawarchiver" / "tasks" / b.get("id", "") / "state.json"
        if not p.exists():
            return {"ok": False, "error": "任务不存在"}
        st = json.loads(p.read_text(encoding="utf-8"))
        st["logs"] = st.get("logs", [])[-80:]
        st.pop("done", None)
        st.pop("to_delete", None)
        return {"ok": True, "state": st}
    if act == "cancel":
        d = Path(out) / ".rawarchiver" / "tasks" / b.get("taskId", "")
        if not d.is_dir():
            return {"ok": False, "error": "任务不存在"}
        (d / "cancel").write_text("1", encoding="utf-8")
        return {"ok": True}
    if act == "cleanup":
        r = json.loads(call("--output", out, "--task-id", b.get("taskId", ""), "--cleanup"))
        r["ok"] = True
        return r
    if act == "rollback":
        r = json.loads(call("--output", out, "--task-id", b.get("taskId", ""), "--rollback"))
        r["ok"] = True
        return r
    return {"ok": False, "error": "未知动作: %s" % act}


MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "RAWArchiverGateway/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 静默访问日志

    def _log_req(self):
        uid = self.headers.get("X-Trim-Userid", "-")
        isadmin = self.headers.get("X-Trim-Isadmin", "-")
        log("REQ %s %s uid=%s admin=%s ua=%s" % (
            self.command, self.path, uid, isadmin,
            self.headers.get("User-Agent", "-")[:60]))

    def _strip_prefix(self):
        parsed = urlparse(self.path)
        p = parsed.path
        if p.startswith(GATEWAY_PREFIX):
            p = p[len(GATEWAY_PREFIX):]
        if not p or p == "/":
            p = "/index.html"
        return p, parsed.query

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data, ctype, status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def do_HEAD(self):
        p, _q = self._strip_prefix()
        self._serve_static(p, head_only=True)

    def do_GET(self):
        self._log_req()
        p, q = self._strip_prefix()
        if p == "/api" or p.startswith("/api"):
            qd = parse_qs(q)
            b = {"action": (qd.get("action", [""])[0]) or "info"}
            self._send_json(handle_action(b, qd))
            return
        self._serve_static(p)

    def do_POST(self):
        self._log_req()
        p, q = self._strip_prefix()
        if p != "/api" and not p.startswith("/api"):
            self._send_json({"ok": False, "error": "not found"}, 404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n > 0 else b""
        except Exception:
            body = b""
        b = {}
        if body:
            try:
                b = json.loads(body.decode("utf-8"))
            except Exception:
                b = {}
        if not isinstance(b, dict):
            b = {}
        qd = parse_qs(q)
        try:
            self._send_json(handle_action(b, qd))
        except subprocess.TimeoutExpired:
            self._send_json({"ok": False, "error": "操作超时"}, 500)
        except Exception as e:
            log("API error: %s" % e)
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _serve_static(self, rel, head_only=False):
        if ".." in rel:
            self._send_json({"ok": False, "error": "bad request"}, 400)
            return
        rel = rel.lstrip("/")
        fpath = os.path.join(WWW, rel) if rel else os.path.join(WWW, "index.html")
        if not os.path.realpath(fpath).startswith(os.path.realpath(WWW)):
            self._send_json({"ok": False, "error": "forbidden"}, 403)
            return
        if os.path.isdir(fpath):
            fpath = os.path.join(fpath, "index.html")
        if not os.path.isfile(fpath):
            self._send_json({"ok": False, "error": "not found"}, 404)
            return
        ext = os.path.splitext(fpath)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(fpath, "rb") as f:
                data = f.read()
        except OSError as e:
            self._send_json({"ok": False, "error": str(e)}, 500)
            return
        if head_only:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return
        self._send_bytes(data, ctype)


class UnixHTTPServer(socketserver.UnixStreamServer):
    allow_reuse_address = True

    def get_request(self):
        request, client_address = super().get_request()
        return request, ("unix", 0)


def main():
    os.makedirs(APP_VAR, exist_ok=True)
    # 清理旧 socket
    if os.path.exists(SOCK_PATH):
        try:
            os.unlink(SOCK_PATH)
        except OSError:
            pass
    os.makedirs(APP_DEST, exist_ok=True)
    log("gateway starting, socket=%s" % SOCK_PATH)
    try:
        server = UnixHTTPServer(SOCK_PATH, Handler)
    except OSError as e:
        log("bind failed: %s" % e)
        sys.stderr.write("bind failed: %s\n" % e)
        sys.exit(1)
    os.chmod(SOCK_PATH, 0o660)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if os.path.exists(SOCK_PATH):
            try:
                os.unlink(SOCK_PATH)
            except OSError:
                pass


if __name__ == "__main__":
    main()
