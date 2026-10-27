#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.0.21 加固项自检（不联网、不需要飞牛真机，只写临时目录）。

与 selftest_dupguard.py（判重口径）互补，这里盯的是「改了容易悄悄改坏」的几处：

  1. taskId 白名单：状态目录 / 日志路径 / 报告路径都不能被 ../ 穿越
  2. 照片批量日期解析：标签集**绝不含 FileModifyDate**（照片无 EXIF ⇒ unknown ⇒ 跳过）
  3. 状态文件写入节流：不再是「每文件两次全量写」
  4. tree_copy 遵循「处理 JPG / 视频」勾选
  5. 清源双重校验：目标文件缺失或大小不符 ⇒ 保留源文件
  6. 网关入参校验：非法 taskId / 非法 days / 源输出互相包含 / 输出不可写 都要明确报错
  7. 核心脚本报错透传：拿得到 stderr 里的真实原因，而不是 "returned non-zero exit status"
  8. 网关多线程：慢请求不阻塞快请求

用法：PYTHONPATH= python3 fnos/selftest_hardening.py
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE / "rawarchiver" / "app"
CORE_DIR = APP / "scripts"
EXIFTOOL = APP / "vendor" / "exiftool" / "exiftool"

ok_n = 0
fail_n = 0


def check(cond, label, extra=""):
    global ok_n, fail_n
    if cond:
        ok_n += 1
        print("  [%02d] ok  %s" % (ok_n + fail_n, label))
    else:
        fail_n += 1
        print("  [%02d] FAIL %s %s" % (ok_n + fail_n, label, extra))


# 1x1 白底 JPEG（无 EXIF），用来测「照片无 EXIF 必须跳过」
TINY_JPG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
    "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")


def make_jpg(path, date=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(TINY_JPG)
    if date:
        subprocess.run([str(EXIFTOOL), "-overwrite_original", "-m",
                        "-DateTimeOriginal=" + date, str(path)],
                       capture_output=True)
    return path


def main():
    tmp = Path(tempfile.mkdtemp(prefix="rawarch_hard_"))
    os.environ["TRIM_PKGVAR"] = str(tmp / "pkgvar")
    sys.path.insert(0, str(CORE_DIR))
    import raw_archiver as core            # noqa: E402
    sys.path.insert(0, str(APP))
    import server                          # noqa: E402

    src = tmp / "src"
    out = tmp / "out"

    print("\n[1] taskId 白名单（防路径穿越）")
    check(core.safe_task_id("20261027_120000_1234") == "20261027_120000_1234", "1a 正常 taskId 通过")
    for bad in ("../../etc", "..", ".", "a/b", "", None, "x" * 65, "a\x00b"):
        check(core.safe_task_id(bad) is None, "1b 拒绝非法 taskId: %r" % (bad,))
    td = core.task_dir("t1")
    check(str(tmp / "pkgvar") in td and td.endswith(os.sep + "t1"), "1c task_dir 落在状态根目录下")
    ok_raise = False
    try:
        core.task_dir("../../../../tmp/evil")
    except ValueError:
        ok_raise = True
    check(ok_raise, "1d task_dir 对穿越 id 抛 ValueError")
    lp = core.log_path(str(out), "t1")
    check(lp.endswith(os.sep + "log" + os.sep + "rawarchiver_t1.log"), "1e log_path 正常")
    ok_raise = False
    try:
        core.log_path(str(out), "../../etc")
    except ValueError:
        ok_raise = True
    check(ok_raise, "1f log_path 对穿越 id 抛 ValueError（不只 task_dir）")
    ok_raise = False
    try:
        core.report_path(str(out), "../x")
    except ValueError:
        ok_raise = True
    check(ok_raise, "1g report_path 对穿越 id 抛 ValueError")

    print("\n[2] 照片日期批量：不得出现 FileModifyDate 兜底")
    check("-FileModifyDate" not in core._ET_PHOTO_DATE_TAGS, "2a 照片标签集不含 -FileModifyDate")
    check("-FileModifyDate" in core._ET_DATE_TAGS, "2b 视频标签集仍含 -FileModifyDate（视频允许兜底）")
    # 造一张「无 EXIF」的照片 + 一张「有 EXIF」的照片，强制走批量路径
    make_jpg(src / "DCIM" / "noexif.jpg")
    make_jpg(src / "DCIM" / "withdate.jpg", "2026:08:01 10:11:12")
    os.utime(src / "DCIM" / "noexif.jpg", (1, 1))       # 老 mtime：若被兜底就会用 1970 年
    old_fast = core._PY_FAST
    core._PY_FAST = False                               # 模拟「没装 exifread / Pillow」
    try:
        d = core.resolve_dates([str(src / "DCIM" / "noexif.jpg"),
                                str(src / "DCIM" / "withdate.jpg")])
    finally:
        core._PY_FAST = old_fast
    noexif = d.get(str(src / "DCIM" / "noexif.jpg"))
    withdate = d.get(str(src / "DCIM" / "withdate.jpg"))
    check(noexif and noexif[0] is None and noexif[1] == "unknown",
          "2c 无 EXIF 照片 ⇒ (None,'unknown')，没有用文件时间兜底", repr(noexif))
    check(withdate and withdate[0] is not None, "2d 有 EXIF 照片仍能拿到日期", repr(withdate))

    print("\n[3] 预览：无日期照片计入 nodate、不被归档")
    prev = core.do_preview(str(src), {"handle_jpg": True, "handle_video": True},
                           limit=500, output=str(out))
    check(prev["counts"]["nodate"] >= 1, "3a 预览把无 EXIF 照片记入 nodate", json.dumps(prev["counts"]))
    check(not Path(str(out)).exists() or not any(Path(str(out)).rglob("*.jpg")),
          "3b 预览不写盘")

    print("\n[4] 状态文件写入节流（不再每文件两次全量写）")
    many = tmp / "many"
    for i in range(40):
        make_jpg(many / ("IMG_%03d.jpg" % i), "2026:08:%02d 09:00:00" % (i % 28 + 1))
    writes = [0]
    orig_aw = core.atomic_write

    def counting(path, obj, indent=2):
        if str(path).endswith("state.json"):
            writes[0] += 1
        return orig_aw(path, obj, indent)

    core.atomic_write = counting
    try:
        st = core.run_task(str(many), str(tmp / "out4"), {"mode": "copy", "handle_jpg": True,
                                                         "handle_video": True, "staging": False},
                           "h4")
    finally:
        core.atomic_write = orig_aw
    check(st["success"] == 40, "4a 40 个文件全部归档", str(st["success"]))
    check(writes[0] < 2 * 40, "4b state.json 写次数 %d < 旧实现下限 %d" % (writes[0], 2 * 40),
          "writes=%d" % writes[0])
    sj = Path(core.task_dir("h4")) / "state.json"
    check(sj.exists() and json.loads(sj.read_text(encoding="utf-8"))["success"] == 40,
          "4c 收尾状态已强制刷盘（current/success 完整）")

    print("\n[5] 断点续跑：同 taskId 再跑不产生副本")
    n_before = len(list(Path(str(tmp / "out4")).rglob("*.jpg")))
    st2 = core.run_task(str(many), str(tmp / "out4"), {"mode": "copy", "handle_jpg": True,
                                                       "handle_video": True, "staging": False},
                        "h4")
    n_after = len(list(Path(str(tmp / "out4")).rglob("*.jpg")))
    check(n_before == n_after == 40, "5a 续跑不新增文件", "%d -> %d" % (n_before, n_after))

    print("\n[6] tree_copy 遵循 handle_jpg 勾选")
    stage = tmp / "stage"
    n, _b = core.tree_copy(str(many), str(stage), {"handle_jpg": False, "handle_video": True})
    check(n == 0 and not list(stage.rglob("*.jpg")), "6a 取消 JPG 时暂存不拷 JPG", "n=%d" % n)
    stage2 = tmp / "stage2"
    n2, _b2 = core.tree_copy(str(many), str(stage2), {"handle_jpg": True, "handle_video": True})
    check(n2 == 40, "6b 勾选 JPG 时正常拷贝", "n=%d" % n2)

    print("\n[7] 清源双重校验：目标不在 / 大小不符 ⇒ 保留源文件")
    mv_src = tmp / "mvs"
    make_jpg(mv_src / "a.jpg", "2026:08:02 08:00:00")
    make_jpg(mv_src / "b.jpg", "2026:08:03 08:00:00")
    mv_out = tmp / "mvo"
    stm = core.run_task(str(mv_src), str(mv_out), {"mode": "move", "handle_jpg": True,
                                                   "handle_video": True, "staging": False},
                        "h7")
    check(stm["success"] == 2 and not list(mv_src.rglob("*.jpg")),
          "7a move 模式：目标落盘后源文件被清空")
    # 再造一个任务，但故意把目标删掉，然后补清源 → 源必须保留
    mv_src2 = tmp / "mvs2"
    make_jpg(mv_src2 / "c.jpg", "2026:08:04 08:00:00")
    mv_out2 = tmp / "mvo2"
    td7 = Path(core.task_dir("h7b"))
    td7.mkdir(parents=True, exist_ok=True)
    (td7 / "state.json").write_text(json.dumps({
        "id": "h7b", "source": str(mv_src2), "output": str(mv_out2), "mode": "move",
        "to_delete": [{"src": "c.jpg", "size": (mv_src2 / "c.jpg").stat().st_size,
                       "dst": "20260804/c.jpg"}],
    }), encoding="utf-8")
    r = core.do_cleanup(str(mv_out2), "h7b")
    check(r["deleted"] == 0 and r["kept"] == ["c.jpg"], "7b 目标缺失 ⇒ 不删源", json.dumps(r))
    # 目标存在且大小一致 → 才删
    (mv_out2 / "20260804").mkdir(parents=True, exist_ok=True)
    shutil.copy2(mv_src2 / "c.jpg", mv_out2 / "20260804" / "c.jpg")
    r2 = core.do_cleanup(str(mv_out2), "h7b")
    check(r2["deleted"] == 1 and not (mv_src2 / "c.jpg").exists(), "7c 目标一致 ⇒ 删源", json.dumps(r2))

    print("\n[8] 网关入参校验")
    check(server.handle_action({"action": "ledger", "op": "prune", "days": "abc"},
                               {})["ok"] is False, "8a days=abc 明确报错")
    check(server.handle_action({"action": "ledger", "op": "prune", "days": -1},
                               {})["ok"] is False, "8b days=-1 被拒（否则会清空台账）")
    check(server.handle_action({"action": "ledger", "op": "prune", "days": 99999},
                               {})["ok"] is False, "8c days=99999 被拒")
    r = server.handle_action({"action": "start", "source": str(many),
                             "output": str(many / "inner")}, {})
    check(r["ok"] is False and "不能互相包含" in r["error"], "8d 输出目录在源目录内 ⇒ 拒绝", r.get("error"))
    # 输出不可写：拿「已存在的普通文件」当输出目录（root 下 chmod 000 也拦不住，用这个更稳）
    afile = tmp / "afile"
    afile.write_text("x", encoding="utf-8")
    r = server.handle_action({"action": "start", "source": str(many),
                             "output": str(afile)}, {})
    check(r["ok"] is False and "不可写" in r["error"], "8e 输出目录不可写 ⇒ 拒绝", r.get("error"))
    r = server.handle_action({"action": "status", "id": "../../etc"}, {})
    check(r["ok"] is False and "非法 taskId" in r["error"], "8f status 穿越 id ⇒ 拒绝", r.get("error"))
    r = server.handle_action({"action": "cancel", "taskId": "../x"}, {})
    check(r["ok"] is False and "非法 taskId" in r["error"], "8g cancel 穿越 id ⇒ 拒绝", r.get("error"))
    r = server.handle_action({"action": "status", "id": "h4"}, {})
    check(r["ok"] is True and r["state"]["success"] == 40, "8h status 仍兼容 id 字段")

    print("\n[9] 核心脚本报错透传（真实原因，不是 exit status）")
    try:
        server.call(str(many), "--output", str(many / "inner"), "--task-id", "t9")
        msg = ""
    except server.CoreError as e:
        msg = str(e)
    check("不能位于源目录内部" in msg, "9a 透传出真实原因（stderr 的 JSON error）", repr(msg))
    # 清源失败不能被包装成成功（核心脚本 ok=false 必须保留）
    _r = server.handle_action({"action": "cleanup", "output": str(tmp / "noout"),
                               "taskId": "nothere"}, {})
    check(_r.get("ok") is False and "state.json 不存在" in str(_r.get("error")),
          "9b 清源失败保留 ok=false（不再被强制改成 true）", json.dumps(_r, ensure_ascii=False))

    print("\n[10] 网关多线程：慢请求不阻塞快请求")
    sock = str(tmp / "t.sock")
    real_handle = server.handle_action

    def slow_handle(b, q):
        if (b.get("action") or "") == "sleepy":
            time.sleep(1.2)
            return {"ok": True, "slept": True}
        return real_handle(b, q)

    server.handle_action = slow_handle
    srv = server.UnixHTTPServer(sock, server.Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    time.sleep(0.2)

    def hit(action):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect(sock)
        s.sendall(("GET /app/rawarchiver/api?action=%s HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
                   % action).encode())
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        return buf

    times = {}

    def worker(name, action):
        t0 = time.time()
        hit(action)
        times[name] = time.time() - t0

    t_slow = threading.Thread(target=worker, args=("slow", "sleepy"))
    t_slow.start()
    time.sleep(0.15)
    t_fast = threading.Thread(target=worker, args=("fast", "info"))
    t_fast.start()
    t_slow.join()
    t_fast.join()
    srv.shutdown()
    srv.server_close()
    server.handle_action = real_handle
    check(times.get("fast", 9) < 0.8 and times.get("slow", 0) > 1.0,
          "10a 慢请求进行中，快请求 %.2fs 内返回（慢请求 %.2fs）"
          % (times.get("fast", -1), times.get("slow", -1)))

    print("\n[11] 网关端到端：preview → start → 轮询 status → done")

    def req_raw(sockpath, method, path, body=None):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(30)
        s.connect(sockpath)
        payload = b""
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
        head = ("%s %s HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                "Content-Length: %d\r\nConnection: close\r\n\r\n" % (method, path, len(payload)))
        s.sendall(head.encode() + payload)
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        _, _, body_b = buf.partition(b"\r\n\r\n")
        return json.loads(body_b.decode("utf-8"))

    e2e_src = tmp / "e2e_src"
    for i in range(5):
        make_jpg(e2e_src / ("E%d.jpg" % i), "2026:09:%02d 07:00:00" % (i + 1))
    e2e_out = tmp / "e2e_out"
    sock2 = str(tmp / "e2e.sock")
    srv2 = server.UnixHTTPServer(sock2, server.Handler)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    time.sleep(0.2)
    pv = req_raw(sock2, "POST", "/app/rawarchiver/api",
                 {"action": "preview", "source": str(e2e_src), "output": str(e2e_out)})
    check(pv.get("ok") and pv["result"]["total"] == 5, "11a 预览拿到 5 个文件", json.dumps(pv)[:200])
    stt = req_raw(sock2, "POST", "/app/rawarchiver/api",
                  {"action": "start", "source": str(e2e_src), "output": str(e2e_out)})
    check(stt.get("ok") is True and stt.get("taskId"), "11b start 返回 taskId", json.dumps(stt))
    tid11 = stt.get("taskId")
    final = None
    for _ in range(60):
        r = req_raw(sock2, "POST", "/app/rawarchiver/api", {"action": "status", "taskId": tid11})
        if r.get("ok") and r["state"]["status"] in ("done", "error", "cancelled"):
            final = r["state"]
            break
        time.sleep(0.25)
    check(final is not None and final["status"] == "done" and final["success"] == 5,
          "11c 轮询到 done 且成功 5 个", json.dumps(final and {k: final[k] for k in
                                                               ("status", "success", "failed")}))
    check(len(list(e2e_out.rglob("*.jpg"))) == 5, "11d 归档落盘 5 个文件")
    # 预览与归档期间，status 一直是可用的（多线程的直接收益）
    r = req_raw(sock2, "POST", "/app/rawarchiver/api", {"action": "status", "id": tid11})
    check(r.get("ok") is True, "11e 归档结束后 status 仍可用（兼容 id 字段）")
    srv2.shutdown()
    srv2.server_close()

    print("\n" + "-" * 60)
    if fail_n:
        print("SELFTEST_HARDENING_FAIL  ok=%d fail=%d" % (ok_n, fail_n))
    else:
        print("SELFTEST_HARDENING_OK  checks=%d" % ok_n)
    shutil.rmtree(str(tmp), ignore_errors=True)
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
