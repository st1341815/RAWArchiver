#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IPC CLI 端到端自测：起 --ipc 子进程，喂 NDJSON，断言响应与事件流。

用法：python tests/test_ipc.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
IPC = os.path.join(HERE, "..", "ipc_main.py")


class Ipc:
    def __init__(self, var):
        env = dict(os.environ, TRIM_PKGVAR=var, PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, IPC, "--ipc"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", env=env, bufsize=1)
        self._lock = threading.Lock()
        self._responses = {}      # id -> dict
        self._events = []         # [dict]
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if "id" in obj and "evt" not in obj:
                with self._lock:
                    self._responses[obj["id"]] = obj
            else:
                with self._lock:
                    self._events.append(obj)

    def call(self, cmd, **kw):
        with self._lock:
            next_id = (max(self._responses.keys()) if self._responses else 0) + 1
        req = {"id": next_id, "cmd": cmd}
        req.update(kw)
        self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        return self._wait_response(next_id)

    def _wait_response(self, rid, timeout=30):
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self._lock:
                if rid in self._responses:
                    return self._responses.pop(rid)
            time.sleep(0.02)
        raise TimeoutError("no response for id %s" % rid)

    def wait_event(self, evt, timeout=60):
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self._lock:
                for i, e in enumerate(self._events):
                    if e.get("evt") == evt:
                        return self._events.pop(i)
            time.sleep(0.05)
        raise TimeoutError("no event %s" % evt)

    def close(self):
        try:
            self.call("shutdown")
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def main():
    from PIL import Image  # noqa: F401

    tmp = tempfile.mkdtemp(prefix="ipc-test-")
    var = os.path.join(tmp, "var")
    src = os.path.join(tmp, "src")
    out = os.path.join(tmp, "out")
    os.makedirs(var)
    os.makedirs(src)

    ex = Image.Exif()
    ex[36867] = "2024:05:06 07:08:09"
    ex[271] = "Canon"
    for n in ("a.jpg", "b.jpg", "c.jpg"):
        Image.new("RGB", (16, 12), (10, 100, 200)).save(
            os.path.join(src, n), exif=ex.tobytes())

    ipc = Ipc(var)
    try:
        # doctor
        r = ipc.call("doctor")
        assert r["ok"] and r["result"]["exifread"] and r["result"]["pillow"], r
        print("doctor OK: exifread=%s pillow=%s exiftool=%s" % (
            r["result"]["exifread"], r["result"]["pillow"], r["result"]["exiftool"]))

        # preview
        r = ipc.call("preview", source=src, output=out,
                     opts={"brandFolder": False, "handleJpg": True,
                           "handleVideo": True, "staging": True, "mode": "copy"})
        assert r["ok"], r
        res = r["result"]
        assert res["total"] == 3 and res["date_range"] == ["2024-05-06", "2024-05-06"], res
        print("preview OK: total=%d date=%s" % (res["total"], res["date_range"]))

        # start + progress + done（小样本会瞬间完成，progress 的 status 可能是 done）
        r = ipc.call("start", source=src, output=out,
                     opts={"mode": "copy", "staging": False}, taskId="ipc001")
        assert r["ok"] and r["result"]["taskId"] == "ipc001", r
        print("start OK: taskId=%s" % r["result"]["taskId"])

        e = ipc.wait_event("progress")
        assert e.get("taskId") == "ipc001", e
        done = ipc.wait_event("done")
        assert done["taskId"] == "ipc001" and done["status"] == "done", done
        assert done["success"] == 3, done
        print("done OK: success=%d failed=%d skipped=%d" % (
            done["success"], done["failed"], done["skipped"]))

        # 落盘校验
        assert os.path.isfile(os.path.join(out, "20240506", "a_20240506.jpg"))
        assert os.path.isfile(os.path.join(out, "log", "rawarchiver_ipc001.log"))
        assert os.path.isfile(os.path.join(var, ".rawarchiver", "tasks", "ipc001", "state.json"))
        print("盘面 OK: 归档落盘 + 日志 + 任务态")

        # cancel 场景：一批文件尽快取消
        src2 = os.path.join(tmp, "src2")
        os.makedirs(src2)
        for i in range(30):
            Image.new("RGB", (64, 48), (i, 50, 80)).save(
                os.path.join(src2, "%03d.jpg" % i), exif=ex.tobytes())
        r = ipc.call("start", source=src2, output=os.path.join(tmp, "out2"),
                     opts={"mode": "copy", "staging": False}, taskId="ipc002")
        assert r["ok"]
        time.sleep(0.3)
        r = ipc.call("cancel", taskId="ipc002")
        assert r["ok"], r
        print("cancel OK")
        # 等到终态（done/cancelled）
        while True:
            e = ipc.wait_event("done")
            if e.get("taskId") == "ipc002":
                assert e["status"] in ("cancelled", "done"), e
                print("cancel 后终态: %s" % e["status"])
                break

        # 未知命令
        r = ipc.call("nope")
        assert r["ok"] is False, r
        print("未知命令报错 OK")

        print("\nSELFTEST_IPC_OK")
    finally:
        ipc.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
