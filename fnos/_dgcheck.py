#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAW 归档 v1.0.19 部署后自检（在 .9 的临时容器里跑，结果写成「文件名」回读）。

容器内约定：/work2 = NAS /vol2。应用 socket = /work2/@appcenter/rawarchiver/rawarchiver.sock
结果目录 = /work2/@appdata/rawarchiver/dgtest/res（空文件名即数据，供 trim-cli file ls 回读）
"""
import json
import os
import shutil
import socket
import time

SOCK = "/work2/@appcenter/rawarchiver/rawarchiver.sock"
# 容器内路径（脚本自己读写用）
BASE = "/work2/@appdata/rawarchiver/dgtest"
# 传给应用 API 的必须是 **NAS 上的真实路径**（应用在容器外跑）
HBASE = "/vol2/@appdata/rawarchiver/dgtest"
HSRC = HBASE + "/src"
HOUT = HBASE + "/out"
SRC = os.path.join(BASE, "src")
OUT = os.path.join(BASE, "out")
RES = os.path.join(BASE, "res")


def mark(name):
    name = name.replace("/", "_").replace(" ", "_")[:200]
    open(os.path.join(RES, name), "w").close()


def req(payload, timeout=60):
    """最小 HTTP/1.1 over unix socket。"""
    body = json.dumps(payload).encode()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(SOCK)
    act = payload.get("action", "")
    s.sendall(("POST /app/rawarchiver/api?action=%s HTTP/1.1\r\n"
               "Host: localhost\r\nContent-Type: application/json\r\n"
               "Content-Length: %d\r\nConnection: close\r\n\r\n" % (act, len(body))).encode()
              + body)
    buf = b""
    while True:
        try:
            d = s.recv(65536)
        except socket.timeout:
            break
        if not d:
            break
        buf += d
    s.close()
    raw = buf.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in buf else buf
    return json.loads(raw.decode("utf-8", "replace"))


def main():
    os.makedirs(RES, exist_ok=True)
    mark("R0_boot")
    # 造 2 个假 MP4（视频走 mtime 兜底，不依赖 EXIF）
    shutil.rmtree(SRC, ignore_errors=True)
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(SRC, "CLIP"), exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    for i, (n, sz, ch) in enumerate([("MVI_9001.MP4", 9000, b"X"), ("MVI_9002.MP4", 9500, b"Y")]):
        p = os.path.join(SRC, "CLIP", n)
        with open(p, "wb") as f:
            f.write(ch * sz)
        t = 1700000000 + i * 60
        os.utime(p, (t, t))
    os.chmod(SRC, 0o777)
    os.chmod(os.path.join(SRC, "CLIP"), 0o777)
    os.chmod(OUT, 0o777)

    # 1 版本
    r = req({"action": "info"})
    mark("R1_info_%s_%s" % (r.get("version"), r.get("mode")))

    # 2 首次预览 → 全 new
    r = req({"action": "preview", "source": HSRC, "output": HOUT})
    c = (r.get("result") or {}).get("counts") or {}
    mark("R2_prev_new%s_dup%s_conf%s" % (c.get("new"), c.get("dup", 0) + c.get("dup_unverified", 0),
                                         c.get("conflict")))

    # 3 归档（skip 策略）
    r = req({"action": "start", "source": HSRC, "output": HOUT, "taskId": "DGC1"})
    mark("R3_start_%s_%s" % (r.get("ok"), r.get("dupPolicy")))
    st = {}
    for _ in range(40):
        time.sleep(1)
        q = req({"action": "status", "id": "DGC1"})
        st = q.get("state") or {}
        if st.get("status") in ("done", "error", "cancelled"):
            break
    mark("R4_done_%s_succ%s_skipdup%s" % (st.get("status"), st.get("success"), st.get("skipped_dup")))

    # 5 再预览 → 全部判为已归档
    r = req({"action": "preview", "source": HSRC, "output": HOUT})
    d = r.get("result") or {}
    c = d.get("counts") or {}
    guard = d.get("dup_guard") or ""
    vol = (d.get("volume") or {}).get("seen_before")
    mark("R5_prev2_dup%s_unver%s_vol%s_guard%s" % (c.get("dup"), c.get("dup_unverified"), vol, bool(guard)))

    # 6 force 无凭据 → 必须被拒
    r = req({"action": "start", "source": HSRC, "output": HOUT, "dupPolicy": "force"})
    mark("R6_force_noguard_%s_%s" % (r.get("ok"), r.get("code")))

    # 7 force 带凭据 → 允许重处理
    r = req({"action": "start", "source": HSRC, "output": HOUT,
             "dupPolicy": "force", "dupGuard": guard, "taskId": "DGC2"})
    mark("R7_force_ok_%s" % r.get("ok"))
    st = {}
    for _ in range(40):
        time.sleep(1)
        q = req({"action": "status", "id": "DGC2"})
        st = q.get("state") or {}
        if st.get("status") in ("done", "error", "cancelled"):
            break
    mark("R8_force_done_%s_succ%s" % (st.get("status"), st.get("success")))

    # 9 目标目录里应有 _1 副本
    n1 = sum(1 for _, _, fns in os.walk(OUT) for f in fns if "_1" in f)
    nall = sum(1 for _, _, fns in os.walk(OUT) for f in fns if f.lower().endswith(".mp4"))
    mark("R9_copies_%d_of_%d" % (n1, nall))

    mark("RZ_all_done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            os.makedirs(RES, exist_ok=True)
            mark("RERR_%s_%s" % (type(e).__name__, str(e)))
        except Exception:
            pass
        raise
