#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAW 归档 —— 本机版 Agent（FastAPI）
用途：NAS CGI 以 http 身份运行、删卡上文件可能没权限时，用本机/root 身份跑同一套核心脚本。
启动：python agent/agent.py   然后浏览器打开 http://127.0.0.1:8765/
"""
import os, sys, json, time, random, shutil, threading, subprocess, webbrowser
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "raw_archiver.py"
APP_NAME = "RAW Archiver"
APP_VER = "1.0.0"

# Web 静态目录在 NAS 布局下是 app/rawarchiver/www，本机同样可用
WWW = ROOT / "app" / "rawarchiver" / "www"

def py():
    venv = ROOT / "agent" / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return str(venv) if venv.exists() else sys.executable

app = FastAPI(title=APP_NAME)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def call(*args, timeout=1800):
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.check_output([py(), "-X", "utf8", str(SCRIPT), *[str(a) for a in args]],
                                   text=True, timeout=timeout, env=env, cwd=str(ROOT))

def list_devices():
    out = []
    if sys.platform == "win32":
        for lit in "DEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{lit}:\\"
            try:
                if Path(root).exists():
                    n = sum(1 for _ in Path(root).rglob("*.JPG"))
                    out.append({"path": root, "label": f"盘 {lit}", "files": n})
            except Exception:
                pass
    else:
        for pat in ("/volumeUSB*/usbshare*", "/media/*/*", "/run/media/*/*", "/mnt/usb*"):
            for d in sorted(ROOT.glob("/*")) if False else sorted(Path("/").glob(pat.lstrip("/"))):
                if d.is_dir():
                    try:
                        n = sum(1 for _ in d.rglob("*.JPG"))
                    except Exception:
                        n = 0
                    out.append({"path": str(d), "label": d.name, "files": n})
    return out

@app.post("/api/index.cgi")
@app.get("/api/index.cgi")
@app.post("/api")
async def api(r: Request):
    try:
        b = await r.json()
    except Exception:
        b = {}
    b = b or {}
    act = b.get("action") or r.query_params.get("action") or "info"
    out = (b.get("output") or "").strip()

    if act == "info":
        return {"ok": True, "app": APP_NAME, "version": APP_VER, "mode": "local-agent",
                "script": str(SCRIPT), "python": py()}
    if act == "doctor":
        return {"ok": True, "result": json.loads(call("--doctor"))}
    if act == "devices":
        return {"ok": True, "list": list_devices()}
    if act == "mkdir":
        p = b.get("path", "")
        if not p:
            return {"ok": False, "error": "path 必填"}
        Path(p).mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": p}
    if act == "preview":
        if not b.get("source"):
            return {"ok": False, "error": "source 必填"}
        return {"ok": True, "result": json.loads(call(b["source"], "--output", out or ".", "--preview", *optargs(b)))}
    if act == "start":
        if not (b.get("source") and out):
            return {"ok": False, "error": "source 与 output 必填"}
        tid = b.get("taskId") or f"{time.strftime('%Y%m%d_%H%M%S')}_{random.randint(1000,9999)}"
        args = [b["source"], "--output", out, "--mode", b.get("mode", "copy"), "--task-id", tid, *optargs(b)]
        logdir = Path(out) / ".rawarchiver" / "tasks" / tid
        logdir.mkdir(parents=True, exist_ok=True)
        lf = open(logdir / "run.log", "a", encoding="utf-8")
        subprocess.Popen([py(), "-X", "utf8", str(SCRIPT), *[str(a) for a in args]],
                         stdout=lf, stderr=subprocess.STDOUT, cwd=str(ROOT))
        return {"ok": True, "taskId": tid}
    if act == "status":
        p = Path(out) / ".rawarchiver" / "tasks" / b.get("id", "") / "state.json"
        if not p.exists():
            return {"ok": False, "error": "任务不存在"}
        st = json.loads(p.read_text(encoding="utf-8"))
        st["logs"] = st.get("logs", [])[-80:]
        st.pop("done", None); st.pop("to_delete", None)
        return {"ok": True, "state": st}
    if act == "cancel":
        d = Path(out) / ".rawarchiver" / "tasks" / b.get("taskId", "")
        if not d.is_dir():
            return {"ok": False, "error": "任务不存在"}
        (d / "cancel").write_text("1", encoding="utf-8")
        return {"ok": True}
    if act == "cleanup":
        return {"ok": True, **json.loads(call("--output", out, "--task-id", b["taskId"], "--cleanup"))}
    if act == "rollback":
        return {"ok": True, **json.loads(call("--output", out, "--task-id", b["taskId"], "--rollback"))}
    return {"ok": False, "error": f"未知动作: {act}"}

def optargs(b):
    a = []
    if b.get("brandFolder"): a.append("--brand")
    if not b.get("handleJpg", True): a.append("--no-jpg")
    if not b.get("handleVideo", True): a.append("--no-video")
    if b.get("monthDir"): a.append("--month")
    a.append("--staging" if b.get("staging", True) else "--no-staging")
    return a

# 前端把 API 拼成 <路径>/api/index.cgi，这里同时挂静态站
app.mount("/", StaticFiles(directory=str(WWW), html=True), name="www")

if __name__ == "__main__":
    print(f"{APP_NAME} v{APP_VER} 本机 Agent: http://127.0.0.1:8765/")
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:8765/")).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
