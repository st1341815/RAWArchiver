#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAW 归档 —— 原生 GUI 的核心引擎 IPC 服务（NDJSON over stdin/stdout）。

GUI（SwiftUI / WPF）作为父进程，spawn 本脚本 `--ipc`，按 PROTOCOL.md 通信。

两种运行模式：
  · `--ipc`        ：IPC 循环（本文件主体，供 GUI 调用）
  · 其它参数        ：原样转发给 scripts/raw_archiver.py 的 CLI（归档 worker 子进程用）

环境约定：
  · TRIM_PKGVAR：任务态目录（GUI 启动本进程前注入；mac: ~/Library/Application Support/RawArchiver，
    win: %APPDATA%\\RawArchiver）
  · 日志与报告由 core 落 <输出目录>/log/（行为不变）
"""

import json
import os
import random
import subprocess
import sys
import threading
import time

FROZEN = bool(getattr(sys, "frozen", False))
HERE = os.path.dirname(os.path.abspath(__file__))

VERSION = "1.1.2"


def _find_core():
    if FROZEN:
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        cands = [
            os.path.join(base, "scripts", "raw_archiver.py"),
            os.path.join(os.path.dirname(sys.executable), "scripts", "raw_archiver.py"),
        ]
    else:
        cands = [os.path.normpath(os.path.join(
            HERE, "..", "..", "fnos", "rawarchiver", "app", "scripts", "raw_archiver.py"))]
    for c in cands:
        if os.path.isfile(c):
            return c
    raise SystemExit("raw_archiver.py not found")


CORE_SCRIPT = _find_core()


def _reconfigure_stdio():
    # Windows 控制台/管道默认编码可能 cp1252/cp936，core 的 print 含中文会崩；
    # 强制 UTF-8（GUI 端按 UTF-8 解码）。
    for s in (sys.stdout, sys.stderr):
        try:
            if s is not None:
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _load_core():
    sys.path.insert(0, os.path.dirname(CORE_SCRIPT))
    import raw_archiver
    return raw_archiver


def worker_cmd(core_args):
    """归档 worker 命令行：frozen 下 = 本 exe 自身（argv 直通 core）；开发态 = 解释器 + core 脚本。"""
    if FROZEN:
        return [sys.executable, *[str(a) for a in core_args]]
    return [sys.executable or "python3", CORE_SCRIPT, *[str(a) for a in core_args]]


def cli_main(argv):
    """直通 core CLI（worker 子进程入口）。"""
    _reconfigure_stdio()
    core = _load_core()
    sys.argv = [CORE_SCRIPT] + argv
    return core.main()


# ---- IPC ----

def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def doctor_result(core):
    binp = core._exiftool_bin()
    return {
        "app": core.APP_NAME,
        "version": VERSION,
        "python": sys.version.split()[0],
        "exifread": core.exifread is not None,
        "pillow": core.Image is not None,
        "exiftool": binp or None,
        "perl": os.path.exists("/usr/bin/perl") or os.path.exists("/opt/homebrew/bin/perl"),
    }


def core_opts(opts):
    """GUI 侧 camelCase → core 侧 snake_case。"""
    return {
        "brand_folder": bool(opts.get("brandFolder", False)),
        "handle_jpg": bool(opts.get("handleJpg", True)),
        "handle_video": bool(opts.get("handleVideo", True)),
        "staging": bool(opts.get("staging", True)),
        "mode": opts.get("mode", "copy"),
        "dup_hash": "full" if opts.get("dupHash") == "full" else "sampled",
        "dup_policy": opts.get("dupPolicy") or "skip",
        "dup_guard": opts.get("dupGuard") or "",
    }


def preview(req, core):
    src = req.get("source", "")
    popts = core_opts(req.get("opts", {}))
    if not src or not os.path.isdir(src):
        raise ValueError("源目录不存在或不可读: %s" % src)
    # output 必须传：判重（已归档/冲突）是按「真实输出目录」算的
    return core.do_preview(src, popts, limit=500, output=req.get("output") or None)


def start_task(req, core):
    src = req.get("source", "")
    out = req.get("output", "")
    opts = core_opts(req.get("opts", {}))
    if not src or not out:
        raise ValueError("source 与 output 必填")
    if not os.path.isdir(src):
        raise ValueError("源目录不存在或不可读: %s" % src)
    # 确认门：重处理已归档必须先在预览里确认过（GUI 勾选 + 二次确认 → 传 dupGuard）
    if opts["dup_policy"] == "force":
        ok_g, err_g = core.check_guard(opts["dup_guard"], src, out, opts)
        if not ok_g:
            raise PermissionError(err_g)

    tid = req.get("taskId") or "%s_%d" % (time.strftime("%Y%m%d_%H%M%S"), random.randint(1000, 9999))
    core_args = [src, "--output", out, "--mode", opts["mode"], "--task-id", tid]
    if opts["brand_folder"]:
        core_args.append("--brand")
    if not opts["handle_jpg"]:
        core_args.append("--no-jpg")
    if not opts["handle_video"]:
        core_args.append("--no-video")
    core_args += ["--dup-hash", opts["dup_hash"]]
    core_args.append("--staging" if opts["staging"] else "--no-staging")
    if opts["dup_policy"] == "force":
        core_args += ["--dup-policy", "force", "--dup-guard", opts["dup_guard"], "--require-guard"]

    logpath = core.log_path(out, tid)
    os.makedirs(os.path.dirname(logpath), exist_ok=True)
    lf = open(logpath, "a", encoding="utf-8")
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    subprocess.Popen(worker_cmd(core_args), stdout=lf, stderr=subprocess.STDOUT, env=env)

    threading.Thread(target=monitor, args=(tid, core), daemon=True).start()
    return {"taskId": tid}


def monitor(tid, core):
    """轮询 state.json，推送 progress 事件（logs 增量）与 done 事件。"""
    last = 0
    while True:
        st = core.load_state(tid)
        if st:
            status = st.get("status", "running")
            logs = st.get("logs", [])
            new_logs = logs[last:] if last <= len(logs) else []
            last = len(logs)
            emit({"evt": "progress", "taskId": tid, "status": status,
                  "current": st.get("current", 0), "total": st.get("total", 0),
                  "success": st.get("success", 0), "failed": st.get("failed", 0),
                  "skipped": st.get("skipped", 0),
                  "skipped_dup": st.get("skipped_dup", 0),
                  "skipped_nodate": st.get("skipped_nodate", 0),
                  "logs": new_logs})
            if status in ("done", "error", "cancelled"):
                emit({"evt": "done", "taskId": tid, "status": status,
                      "success": st.get("success", 0), "failed": st.get("failed", 0),
                      "skipped": st.get("skipped", 0),
                      "skipped_dup": st.get("skipped_dup", 0),
                      "skipped_nodate": st.get("skipped_nodate", 0),
                      "error": st.get("error", "")})
                break
        time.sleep(0.5)


def cancel_task(req, core):
    d = core.task_dir(req.get("taskId", ""))
    if not os.path.isdir(d):
        raise ValueError("任务不存在")
    with open(os.path.join(d, "cancel"), "w", encoding="utf-8") as f:
        f.write("1")
    return {}


def cleanup(req, core):
    return core.do_cleanup(req.get("output", ""), req.get("taskId", ""),
                           bool(req.get("verifyHash", False)))


def rollback(req, core):
    return core.do_rollback(req.get("output", ""), req.get("taskId", ""))


def ipc_main():
    _reconfigure_stdio()
    core = _load_core()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            emit({"id": None, "ok": False, "error": "bad request"})
            continue
        if not isinstance(req, dict):
            emit({"id": None, "ok": False, "error": "bad request"})
            continue
        rid = req.get("id")
        cmd = req.get("cmd")
        try:
            if cmd == "doctor":
                result = doctor_result(core)
            elif cmd == "preview":
                result = preview(req, core)
            elif cmd == "start":
                result = start_task(req, core)
            elif cmd == "cancel":
                result = cancel_task(req, core)
            elif cmd == "cleanup":
                result = cleanup(req, core)
            elif cmd == "rollback":
                result = rollback(req, core)
            elif cmd == "shutdown":
                emit({"id": rid, "ok": True, "result": {}})
                break
            else:
                emit({"id": rid, "ok": False, "error": "未知命令: %s" % cmd})
                continue
            emit({"id": rid, "ok": True, "result": result})
        except Exception as e:
            emit({"id": rid, "ok": False, "error": str(e)})
    return 0


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--ipc":
        return ipc_main()
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
