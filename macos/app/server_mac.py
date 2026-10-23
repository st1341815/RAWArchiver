#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAW 归档 —— macOS 本地服务（TCP 版，复刻 fnos 统一网关服务）。

监听 127.0.0.1 随机端口（仅本机），提供：
  - 静态文件（www/，与 fnos 版同一份 index.html）
  - JSON API（info/doctor/devices/browse/mkdir/preview/start/status/cancel/cleanup/rollback）
  - 简易 token 鉴权（URL ?t=，前端从地址栏取出后随每个 API 请求回传）

与 fnos 版（fnos/rawarchiver/app/server.py）的差异只有平台适配层：
  1. Unix Socket（网关转发）→ 127.0.0.1 TCP + token（pywebview/WKWebView 直接加载）
  2. 归档 worker：frozen（PyInstaller）下用打包后的应用二进制自身转发 CLI；
     开发态下用当前解释器直接跑 scripts/raw_archiver.py
  3. 设备扫描：/Volumes/*（macOS 外接卷），fnOS 的 /vol00、DSM 的 volumeUSB 不适用
  4. info 返回 mode="macos"（前端据此走 pywebview 目录选择分支）
  5. 源目录不可读的提示文案改为 macOS 语境

所有实际归档逻辑仍在 scripts/raw_archiver.py（只用标准库 + exifread/Pillow），
本服务只做参数转发与状态读取——与 fnos 版职责一致。

盘面约定（v1.0.14 起，macOS 对应关系）：
  · 任务状态（state.json / cancel / 暂存）→ ~/Library/Application Support/RawArchiver/.rawarchiver/
    （由 main_mac.py 注入 TRIM_PKGVAR 环境变量实现，核心脚本零改动）
  · 运行日志与报告 → <输出目录>/log/（rawarchiver_<tid>.log、_report_<tid>.json）
  · 源目录只读，任何情况下不产生文件或文件夹
"""

import os
import sys
import json
import random
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_NAME = "rawarchiver"
GATEWAY_PREFIX = "/app/" + APP_NAME

SELF = os.path.abspath(__file__)
# 开发态：macos/app/；PyInstaller onedir：Contents/Resources/
APP_DEST = os.path.dirname(SELF)
SCRIPT = os.path.join(APP_DEST, "scripts", "raw_archiver.py")
WWW = os.path.join(APP_DEST, "www")
APP_VAR = os.environ.get("TRIM_PKGVAR") or os.path.expanduser(
    "~/Library/Application Support/RawArchiver")

FROZEN = bool(getattr(sys, "frozen", False))

# 状态目录 / 日志路径的唯一来源 = 核心脚本，避免两处规则漂移
sys.path.insert(0, os.path.join(APP_DEST, "scripts"))
import raw_archiver as core  # noqa: E402

VERSION = "1.0.18"  # 与 fnos 版保持同版本号

# 本机 API 鉴权 token：main_mac.py 启动时生成并拼进窗口 URL，前端从
# location.search 取出后随每个 /api 请求回传（query 参数 t）。
TOKEN = secrets.token_hex(16)


def task_dir(tid):
    """任务状态目录（应用数据目录下）。"""
    return core.task_dir(tid)


def log_file(out, tid):
    """运行日志落 <输出目录>/log/rawarchiver_<tid>.log。"""
    return core.log_path(out, tid)


def log(msg):
    try:
        os.makedirs(APP_VAR, exist_ok=True)
        with open(os.path.join(APP_VAR, "gateway.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def worker_cmd(args):
    """归档 worker 命令行。

    frozen：打包后的应用二进制自身（main_mac.py 判定 argv 非空 → 转发 core CLI）；
    开发态：当前解释器直接跑核心脚本（与 fnos 版行为一致）。
    """
    if FROZEN:
        return [sys.executable, *[str(a) for a in args]]
    return [sys.executable or "python3", "-X", "utf8", SCRIPT,
            *[str(a) for a in args]]


def call(*args, timeout=1800):
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.check_output(
        worker_cmd(args), text=True, timeout=timeout, env=env, cwd=APP_DEST)


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
    """macOS：/Volumes/ 下的外接卷（SD 卡 / U 盘 / 移动硬盘）。"""
    out = []

    ARCHIVE_EXTS = {'.jpg', '.jpeg', '.nef', '.nrw', '.cr2', '.cr3', '.crw', '.arw',
                    '.srf', '.sr2', '.raf', '.orf', '.dng', '.pef', '.rw2',
                    '.mp4', '.mov', '.mts', '.m2ts', '.avi', '.mkv', '.3gp',
                    '.mpg', '.mpeg', '.wmv', '.flv', '.m4v', '.ts', '.mod', '.mxf'}

    def count_files(root):
        try:
            return sum(1 for _ in Path(root).rglob("*")
                       if _.is_file() and _.suffix.lower() in ARCHIVE_EXTS)
        except Exception:
            return 0

    vol = Path("/Volumes")
    try:
        for d in sorted(vol.iterdir(), key=lambda c: c.name.lower()):
            if d.name.startswith(".") or not d.is_dir():
                continue
            out.append({"path": str(d), "label": d.name, "files": count_files(d)})
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


def check_source_readable(src):
    """返回 None 表示可读；否则返回错误文案（macOS 语境）。"""
    if not src:
        return "源目录必填"
    if not os.path.isdir(src):
        return "源目录不存在: %s（SD 卡 / U 盘请先插入，桌面应在「访达」侧栏看到它）" % src
    if not os.access(src, os.R_OK | os.X_OK):
        return ("无法读取源目录（没有访问权限）: %s 。"
                "请在「访达」中右键该文件夹 → 显示简介 → 共享与权限，"
                "确认当前用户可读；或换一个位置（如把卡里的 DCIM 拷到「下载」再试）。" % src)
    return None


def handle_action(b, q):
    act = b.get("action") or (q.get("action", [""])[0]) or "info"
    out = (b.get("output") or "").strip()

    if act == "info":
        return {"ok": True, "app": "RAW 归档", "version": VERSION, "mode": "macos",
                "script": SCRIPT, "python": sys.executable or "python3"}
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
        src = (b.get("source") or "").strip()
        err = check_source_readable(src)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "result": json.loads(
            call(src, "--output", out or ".", "--preview", *optargs(b)))}
    if act == "start":
        if not (b.get("source") and out):
            return {"ok": False, "error": "source 与 output 必填"}
        src = (b.get("source") or "").strip()
        err = check_source_readable(src)
        if err:
            return {"ok": False, "error": err}
        tid = b.get("taskId") or "%s_%d" % (time.strftime("%Y%m%d_%H%M%S"), random.randint(1000, 9999))
        args = [src, "--output", out, "--mode", b.get("mode", "copy"),
                "--task-id", tid, *optargs(b)]
        lf_path = log_file(out, tid)
        Path(lf_path).parent.mkdir(parents=True, exist_ok=True)
        lf = open(lf_path, "a", encoding="utf-8")
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        subprocess.Popen(worker_cmd(args), stdout=lf, stderr=subprocess.STDOUT,
                         cwd=APP_DEST, env=env)
        return {"ok": True, "taskId": tid}
    if act == "status":
        p = Path(task_dir(b.get("id", ""))) / "state.json"
        if not p.exists():
            return {"ok": False, "error": "任务不存在"}
        st = json.loads(p.read_text(encoding="utf-8"))
        st["logs"] = st.get("logs", [])[-80:]
        st.pop("done", None)
        st.pop("to_delete", None)
        return {"ok": True, "state": st}
    if act == "cancel":
        d = Path(task_dir(b.get("taskId", "")))
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
    server_version = "RAWArchiverMac/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 静默访问日志

    def _check_token(self, qd):
        t = (qd.get("t", [""])[0]) or self.headers.get("X-RA-Token", "")
        return t == TOKEN

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
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _send_bytes(self, data, ctype, status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def do_GET(self):
        p, q = self._strip_prefix()
        qd = parse_qs(q)
        if p == "/api" or p.startswith("/api"):
            if not self._check_token(qd):
                self._send_json({"ok": False, "error": "invalid token"}, 403)
                return
            b = {"action": (qd.get("action", [""])[0]) or "info"}
            try:
                self._send_json(handle_action(b, qd))
            except subprocess.TimeoutExpired:
                self._send_json({"ok": False, "error": "操作超时"}, 500)
            except Exception as e:
                log("API error: %s" % e)
                self._send_json({"ok": False, "error": str(e)}, 500)
            return
        self._serve_static(p)

    def do_POST(self):
        p, q = self._strip_prefix()
        qd = parse_qs(q)
        if p != "/api" and not p.startswith("/api"):
            self._send_json({"ok": False, "error": "not found"}, 404)
            return
        if not self._check_token(qd):
            self._send_json({"ok": False, "error": "invalid token"}, 403)
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
        try:
            self._send_json(handle_action(b, qd))
        except subprocess.TimeoutExpired:
            self._send_json({"ok": False, "error": "操作超时"}, 500)
        except Exception as e:
            log("API error: %s" % e)
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _serve_static(self, rel):
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
        self._send_bytes(data, ctype)


def make_server():
    """起 127.0.0.1 随机端口的 HTTP 服务，返回 (server, port)。"""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    return srv, srv.server_address[1]


def serve_forever():
    """开发态独立运行入口：python3 server_mac.py（无 GUI）。"""
    os.makedirs(APP_VAR, exist_ok=True)
    srv, port = make_server()
    url = "http://127.0.0.1:%d%s/?t=%s" % (port, GATEWAY_PREFIX, TOKEN)
    print("RAW 归档 macOS 服务已启动: %s" % url, flush=True)
    log("server starting on 127.0.0.1:%d" % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    serve_forever()
