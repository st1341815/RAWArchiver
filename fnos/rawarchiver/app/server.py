#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAW 归档 —— fnOS 统一网关常驻服务。

监听 Unix Socket（TRIM_APPDEST/rawarchiver.sock），提供：
  - 静态文件（www/）
  - JSON API（复用原 api/index.cgi 的动作：info/doctor/devices/browse/mkdir/preview/start/status/cancel/cleanup/rollback）

网关转发请求路径形如 /app/rawarchiver/...，本服务会剥离前缀后映射到 www/ 或 /api。
所有实际归档逻辑仍在 scripts/raw_archiver.py（只用标准库），本服务只做参数转发与状态读取。

盘面约定（v1.0.14 起）：
  · 任务状态（state.json / cancel / 暂存）→ 应用运行的主目录 $TRIM_PKGVAR/.rawarchiver/tasks/<tid>/
  · 运行日志与报告 → <输出目录>/log/（rawarchiver_<tid>.log、_report_<tid>.json）
  · 源目录只读，任何情况下不产生文件或文件夹
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

# 状态目录 / 日志路径的唯一来源 = 核心脚本，避免两处规则漂移
sys.path.insert(0, os.path.join(APP_DEST, "scripts"))
import raw_archiver as core  # noqa: E402

VERSION = "1.0.22"


class CoreError(Exception):
    """核心脚本以非 0 退出时抛出，message 为它 stderr 里的真实原因。"""

    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def _core_error(r):
    """从核心脚本的 stderr 里挑出最有信息量的一行（优先 JSON 的 error 字段）。

    核心脚本的错误约定是「stderr 输出 {"ok": false, "error": ...} + 退出码 1」。
    之前用 check_output 只留 stdout，真实原因会被
    "Command '...' returned non-zero exit status 1." 整个吞掉。
    """
    lines = [x.strip() for x in (r.stderr or '').strip().splitlines() if x.strip()]
    for ln in reversed(lines):
        if ln.startswith('{'):
            try:
                o = json.loads(ln)
                if isinstance(o, dict) and o.get('error'):
                    return str(o['error'])
            except Exception:
                pass
        if ln.startswith('['):          # 核心脚本的日志行：[时间] 内容
            return ln.split('] ', 1)[-1]
    if lines:
        return lines[-1]
    return '核心脚本执行失败（无 stderr 输出）'


def _tail_text(path):
    """取运行日志尾部最有信息量的一行（用于「启动即失败」时回给前端）。"""
    try:
        data = Path(path).read_text(encoding='utf-8', errors='replace')
    except Exception:
        return ''
    lines = [x.strip() for x in data.strip().splitlines() if x.strip()]
    for ln in reversed(lines):
        if ln.startswith('{'):
            try:
                o = json.loads(ln)
                if isinstance(o, dict) and o.get('error'):
                    return str(o['error'])
            except Exception:
                pass
        if ln.startswith('['):
            return ln.split('] ', 1)[-1]
    return lines[-1][:300] if lines else ''


def task_dir(tid):
    """任务状态目录（应用数据目录下）。"""
    return core.task_dir(tid)


def log_file(out, tid):
    """运行日志落 <输出目录>/log/rawarchiver_<tid>.log。"""
    return core.log_path(out, tid)


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
    """跑一次核心脚本 CLI，返回 stdout。

    非 0 退出时抛 CoreError（携带 stderr 里的真实原因），而不是把原因丢掉。
    """
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    cmd = [pybin(), "-X", "utf8", SCRIPT, *[str(a) for a in args]]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       env=env, cwd=APP_DEST)
    if r.returncode != 0:
        raise CoreError(_core_error(r), r.returncode)
    return r.stdout


def _tid(b):
    """统一取任务ID（status 历史上用 id、其余用 taskId，这里两个都认）。"""
    return b.get("taskId") or b.get("id") or ""


def _clean_tid(b):
    """取并清洗任务ID；非法返回 None。"""
    return core.safe_task_id(_tid(b))


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
    a += ["--dup-hash", "full" if b.get("dupHash") == "full" else "sampled"]
    a.append("--staging" if b.get("staging", True) else "--no-staging")
    return a


def dup_opts(b):
    """GUI 的重复处理策略 → core 的 opts（供确认门校验）。"""
    return {
        "brand_folder": bool(b.get("brandFolder")),
        "handle_jpg": b.get("handleJpg") is not False,
        "handle_video": b.get("handleVideo") is not False,
        "month_dir": bool(b.get("monthDir")),
        "staging": bool(b.get("staging", True)),
        "mode": b.get("mode", "copy"),
        "dup_hash": "full" if b.get("dupHash") == "full" else "sampled",
    }


def list_devices():
    out = []

    # 可归档扩展名 = 核心脚本的 ALL_EXTS 单一真源（不再本地维护一份，避免漂移）
    ARCHIVE_EXTS = core.ALL_EXTS

    def count_files(root):
        try:
            return sum(1 for _ in Path(root).rglob("*")
                       if _.is_file() and _.suffix.lower() in ARCHIVE_EXTS)
        except Exception:
            return 0

    # 飞牛 fnOS 外接存储挂载在 /vol00/<设备名>（如 /vol00/MassStorageClass）；
    # 与 DSM 的 /volumeUSB*/usbshare* 不同——后者一并保留以兼容群晖。
    for pat in ("vol00/*", "volumeUSB*/usbshare*", "volumeUSB*/usbshare",
                "media/*/*", "run/media/*/*", "mnt/usb*"):
        try:
            for d in sorted(Path("/").glob(pat)):
                if d.is_dir():
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
    """返回 None 表示可读；否则返回错误文案。

    飞牛外接存储（/vol00，FAT 挂载、默认只对 root 可见）对应用用户不可读时，
    os.walk 会静默返回空（预览显示 0 个文件）。这里提前给出明确提示。
    解决办法：飞牛「文件管理 → 设置 → 外接存储权限」设为「所有账户可见」。
    """
    if not src:
        return "源目录必填"
    if not os.path.isdir(src):
        return "源目录不存在: %s" % src
    if not os.access(src, os.R_OK | os.X_OK):
        return "无法读取源目录（没有访问权限）。请到飞牛「文件管理 → 设置 → 外接存储权限」设为「所有账户可见」后重试: %s" % src
    return None


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
        src = (b.get("source") or "").strip()
        err = check_source_readable(src)
        if err:
            return {"ok": False, "error": err}
        args = [src, "--preview"]
        if out:
            args += ["--output", out]
        return {"ok": True, "result": json.loads(call(*args, *optargs(b)))}
    if act == "start":
        if not (b.get("source") and out):
            return {"ok": False, "error": "source 与 output 必填"}
        src = (b.get("source") or "").strip()
        err = check_source_readable(src)
        if err:
            return {"ok": False, "error": err}
        # 前置校验（与核心脚本 CLI 同口径）：别等子进程起来再失败，前端却显示"已开始"
        if core.path_inside(out, src) or core.path_inside(src, out):
            return {"ok": False, "error": "源目录与输出目录不能互相包含（输出目录不能位于源目录内，反之亦然）"}
        try:
            Path(out).mkdir(parents=True, exist_ok=True)
            probe = Path(out) / ".write_test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except Exception as e:
            return {"ok": False, "error": "输出目录不可写: %s" % e}
        # 确认门：重处理已归档必须先在预览里确认过（凭据由预览签发，30 分钟有效）
        policy = b.get("dupPolicy") or "skip"
        if policy not in ("skip", "force"):
            return {"ok": False, "error": "dupPolicy 非法: %s" % policy}
        if policy == "force":
            ok_g, err_g = core.check_guard(b.get("dupGuard"), src, out, dup_opts(b))
            if not ok_g:
                return {"ok": False, "code": "need_confirm", "error": err_g}
        given = b.get("taskId")
        if given:
            tid = core.safe_task_id(given)
            if not tid:
                return {"ok": False, "error": "非法 taskId: %r" % (given,)}
        else:
            tid = "%s_%d" % (time.strftime("%Y%m%d_%H%M%S"), random.randint(1000, 9999))
        args = [src, "--output", out, "--mode", b.get("mode", "copy"),
                "--task-id", tid, *optargs(b)]
        if policy == "force":
            args += ["--dup-policy", "force", "--dup-guard", str(b.get("dupGuard") or "")]
        lf_path = log_file(out, tid)
        Path(lf_path).parent.mkdir(parents=True, exist_ok=True)
        with open(lf_path, "a", encoding="utf-8") as lf:
            proc = subprocess.Popen([pybin(), "-X", "utf8", SCRIPT, *[str(a) for a in args]],
                                    stdout=lf, stderr=subprocess.STDOUT, cwd=APP_DEST)
        # 抓「起来就失败」的常见情形（凭据/权限/路径）：0.4s 内非 0 退出就直接回报原因
        time.sleep(0.4)
        rc = proc.poll()
        if rc is not None and rc != 0:
            reason = _tail_text(lf_path)
            return {"ok": False, "taskId": tid,
                    "error": "任务启动失败：%s（详见 %s）" % (reason or "见运行日志", lf_path)}
        return {"ok": True, "taskId": tid, "dupPolicy": policy}
    if act == "ledger":
        op = b.get("op") or "stats"
        if op == "stats":
            return core.ledger_stats(out or None)
        if op == "rebuild":
            if not out:
                return {"ok": False, "error": "rebuild 需 output"}
            conn = core.ledger_conn()
            try:
                n = core.rebuild_from_reports(conn, out)
                conn.commit()
            finally:
                conn.close()
            return {"ok": True, "added": n, "output": out}
        if op == "prune":
            try:
                days = int(b.get("days") or 180)
            except (TypeError, ValueError):
                return {"ok": False, "error": "days 必须为整数"}
            if days < 1 or days > 3650:
                return {"ok": False, "error": "days 需在 1~3650 之间"}
            return core.ledger_prune(out or None, days)
        return {"ok": False, "error": "未知 op: %s" % op}
    if act == "status":
        tid = _clean_tid(b)
        if not tid:
            return {"ok": False, "error": "非法 taskId: %r" % (_tid(b),)}
        p = Path(task_dir(tid)) / "state.json"
        if not p.exists():
            return {"ok": False, "error": "任务不存在"}
        st = json.loads(p.read_text(encoding="utf-8"))
        st["logs"] = st.get("logs", [])[-80:]
        st.pop("done", None)
        st.pop("to_delete", None)
        return {"ok": True, "state": st}
    if act == "cancel":
        tid = _clean_tid(b)
        if not tid:
            return {"ok": False, "error": "非法 taskId: %r" % (_tid(b),)}
        d = Path(task_dir(tid))
        if not d.is_dir():
            return {"ok": False, "error": "任务不存在"}
        (d / "cancel").write_text("1", encoding="utf-8")
        return {"ok": True}
    if act == "cleanup":
        tid = _clean_tid(b)
        if not tid:
            return {"ok": False, "error": "非法 taskId: %r" % (_tid(b),)}
        r = json.loads(call("--output", out, "--task-id", tid, "--cleanup"))
        r.setdefault("ok", True)      # 保留核心脚本的 ok=false（失败别显示成成功）
        return r
    if act == "rollback":
        tid = _clean_tid(b)
        if not tid:
            return {"ok": False, "error": "非法 taskId: %r" % (_tid(b),)}
        r = json.loads(call("--output", out, "--task-id", tid, "--rollback"))
        r.setdefault("ok", True)
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
        except CoreError as e:
            # 核心脚本的真实报错（路径不可写/凭据失效/目录互相包含…）原样回给前端
            self._send_json({"ok": False, "error": str(e)}, 400)
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


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """多线程处理：preview / devices 这类长调用不再把 status 轮询与取消按钮一起卡死。

    之前是单线程 UnixStreamServer，一次 preview（扫整卡 + 解析日期，最长 1800s）
    会把所有并发请求排在后面 —— 前端每 1.5s 轮询一次 status，全部堵住。
    """
    allow_reuse_address = True
    daemon_threads = True

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
