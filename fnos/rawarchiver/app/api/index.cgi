#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAW 归档 —— fnOS JSON API（CGI）。

请求：POST，body 为 JSON {"action": ..., ...}（action 也可放在 query 上）。
响应：Content-Type: application/json，body 为单个 JSON。

动作：info / doctor / devices / browse / mkdir / preview / start / status / cancel / cleanup / rollback / ledger
重复归档防护：preview 返回 counts/dup/volume/dup_guard；start 支持 dupPolicy=skip|force（force 需 dupGuard）。
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

# 状态目录 / 日志路径的唯一来源 = 核心脚本（与 server.py 同一套规则）
sys.path.insert(0, os.path.join(APP_DEST, "scripts"))
import raw_archiver as core  # noqa: E402


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


class CoreError(Exception):
    """核心脚本以非 0 退出时抛出，message 为它 stderr 里的真实原因。"""


def _core_error(r):
    """从核心脚本 stderr 里挑出最有信息量的一行（优先 JSON 的 error 字段）。"""
    lines = [x.strip() for x in (r.stderr or "").strip().splitlines() if x.strip()]
    for ln in reversed(lines):
        if ln.startswith("{"):
            try:
                o = json.loads(ln)
                if isinstance(o, dict) and o.get("error"):
                    return str(o["error"])
            except Exception:
                pass
        if ln.startswith("["):
            return ln.split("] ", 1)[-1]
    return lines[-1] if lines else "核心脚本执行失败（无 stderr 输出）"


def call(*args, timeout=1800):
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    cmd = [pybin(), "-X", "utf8", SCRIPT, *[str(a) for a in args]]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       env=env, cwd=APP_DEST)
    if r.returncode != 0:
        raise CoreError(_core_error(r))
    return r.stdout


def _tid(b):
    """统一取任务ID（兼容 status 历史上的 id 字段）。"""
    return b.get("taskId") or b.get("id") or ""


def _clean_tid(b):
    return core.safe_task_id(_tid(b))


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
    a += ["--dup-hash", "full" if b.get("dupHash") == "full" else "sampled"]
    a.append("--staging" if b.get("staging", True) else "--no-staging")
    return a


def dup_opts(b):
    return {"brand_folder": bool(b.get("brandFolder")),
            "handle_jpg": b.get("handleJpg") is not False,
            "handle_video": b.get("handleVideo") is not False,
            "month_dir": bool(b.get("monthDir")),
            "staging": bool(b.get("staging", True)),
            "mode": b.get("mode", "copy"),
            "dup_hash": "full" if b.get("dupHash") == "full" else "sampled"}


def list_devices():
    out = []

    ARCHIVE_EXTS = core.ALL_EXTS   # 单一真源，别再本地维护一份（曾漂移成只数 .JPG/.jpg，漏 .jpeg）

    def count_files(root):
        try:
            return sum(1 for _ in Path(root).rglob("*")
                       if _.is_file() and _.suffix.lower() in ARCHIVE_EXTS)
        except Exception:
            return 0

    for pat in ("volumeUSB*/usbshare*", "volumeUSB*/usbshare", "media/*/*", "run/media/*/*", "mnt/usb*"):
        try:
            for d in sorted(Path("/").glob(pat)):
                if d.is_dir():
                    out.append({"path": str(d), "label": d.name, "files": count_files(d)})
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
        emit({"ok": True, "app": "RAW 归档", "version": "1.0.22", "mode": "fnos-cgi",
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
            args = [b["source"], "--preview"]
            if out:
                args += ["--output", out]
            emit({"ok": True, "result": json.loads(call(*args, *optargs(b)))})
    elif act == "start":
        if not (b.get("source") and out):
            emit({"ok": False, "error": "source 与 output 必填"})
        elif (b.get("dupPolicy") or "skip") not in ("skip", "force"):
            emit({"ok": False, "error": "dupPolicy 非法: %s" % b.get("dupPolicy")})
        elif (b.get("dupPolicy") or "skip") == "force" and not core.check_guard(
                b.get("dupGuard"), b["source"], out, dup_opts(b))[0]:
            _ok, _err = core.check_guard(b.get("dupGuard"), b["source"], out, dup_opts(b))
            emit({"ok": False, "code": "need_confirm", "error": _err})
        elif core.path_inside(out, b["source"]) or core.path_inside(b["source"], out):
            emit({"ok": False, "error": "源目录与输出目录不能互相包含（输出目录不能位于源目录内，反之亦然）"})
        elif not os.access(b["source"], os.R_OK | os.X_OK):
            emit({"ok": False, "error": "无法读取源目录（没有访问权限）: %s" % b["source"]})
        else:
            try:
                Path(out).mkdir(parents=True, exist_ok=True)
                probe = Path(out) / ".write_test"
                probe.write_text("", encoding="utf-8")
                probe.unlink()
            except Exception as e:
                emit({"ok": False, "error": "输出目录不可写: %s" % e})
                return
            given = b.get("taskId")
            tid = core.safe_task_id(given) if given else "%s_%d" % (
                time.strftime("%Y%m%d_%H%M%S"), random.randint(1000, 9999))
            if not tid:
                emit({"ok": False, "error": "非法 taskId: %r" % (given,)})
                return
            args = [b["source"], "--output", out, "--mode", b.get("mode", "copy"),
                    "--task-id", tid, *optargs(b)]
            if (b.get("dupPolicy") or "skip") == "force":
                args += ["--dup-policy", "force", "--dup-guard", str(b.get("dupGuard") or "")]
            lf_path = core.log_path(out, tid)
            Path(lf_path).parent.mkdir(parents=True, exist_ok=True)
            with open(lf_path, "a", encoding="utf-8") as lf:
                proc = subprocess.Popen([pybin(), "-X", "utf8", SCRIPT, *[str(a) for a in args]],
                                        stdout=lf, stderr=subprocess.STDOUT, cwd=APP_DEST)
            time.sleep(0.4)
            rc = proc.poll()
            if rc is not None and rc != 0:
                emit({"ok": False, "taskId": tid,
                      "error": "任务启动失败（详见 %s）" % lf_path})
            else:
                emit({"ok": True, "taskId": tid})
    elif act == "status":
        _t = _clean_tid(b)
        if not _t:
            emit({"ok": False, "error": "非法 taskId: %r" % (_tid(b),)})
            return
        p = Path(core.task_dir(_t)) / "state.json"
        if not p.exists():
            emit({"ok": False, "error": "任务不存在"})
        else:
            st = json.loads(p.read_text(encoding="utf-8"))
            st["logs"] = st.get("logs", [])[-80:]
            st.pop("done", None)
            st.pop("to_delete", None)
            emit({"ok": True, "state": st})
    elif act == "cancel":
        _t = _clean_tid(b)
        if not _t:
            emit({"ok": False, "error": "非法 taskId: %r" % (_tid(b),)})
            return
        d = Path(core.task_dir(_t))
        if not d.is_dir():
            emit({"ok": False, "error": "任务不存在"})
        else:
            (d / "cancel").write_text("1", encoding="utf-8")
            emit({"ok": True})
    elif act == "cleanup":
        _t = _clean_tid(b)
        if not _t:
            emit({"ok": False, "error": "非法 taskId: %r" % (_tid(b),)})
            return
        _r = json.loads(call("--output", out, "--task-id", _t, "--cleanup"))
        _r.setdefault("ok", True)      # 保留核心脚本的 ok=false（失败别显示成成功）
        emit(_r)
    elif act == "ledger":
        op = b.get("op") or "stats"
        if op == "stats":
            emit(core.ledger_stats(out or None))
        elif op == "rebuild":
            if not out:
                emit({"ok": False, "error": "rebuild 需 output"})
            else:
                conn = core.ledger_conn()
                try:
                    n = core.rebuild_from_reports(conn, out)
                    conn.commit()
                finally:
                    conn.close()
                emit({"ok": True, "added": n, "output": out})
        elif op == "prune":
            try:
                _days = int(b.get("days") or 180)
            except (TypeError, ValueError):
                emit({"ok": False, "error": "days 必须为整数"})
                return
            if _days < 1 or _days > 3650:
                emit({"ok": False, "error": "days 需在 1~3650 之间"})
                return
            emit(core.ledger_prune(out or None, _days))
        else:
            emit({"ok": False, "error": "未知 op: %s" % op})
    elif act == "rollback":
        _t = _clean_tid(b)
        if not _t:
            emit({"ok": False, "error": "非法 taskId: %r" % (_tid(b),)})
            return
        _r = json.loads(call("--output", out, "--task-id", _t, "--rollback"))
        _r.setdefault("ok", True)
        emit(_r)
    else:
        emit({"ok": False, "error": "未知动作: %s" % act})


if __name__ == "__main__":
    try:
        main()
    except CoreError as e:
        # 核心脚本的真实报错（路径/权限/凭据）原样回给前端，而不是抛 traceback
        emit({"ok": False, "error": str(e)})
    except Exception as e:
        emit({"ok": False, "error": str(e)})
