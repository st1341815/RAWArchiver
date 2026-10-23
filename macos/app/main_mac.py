#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAW 归档 —— macOS 应用入口。

两种运行方式：
  1. 无参数（双击 .app）：起本地 HTTP 服务（server_mac）+ pywebview 原生窗口（WKWebView）。
     窗口标题「RAW 归档」，目录选择走 macOS 系统文件夹选择框（NSOpenPanel）。
     pywebview 不可用时回落默认浏览器打开（服务保持运行）。
  2. 带参数（终端 / server 子进程 worker）：原样转发给 scripts/raw_archiver.py 的 CLI
     （preview/start/doctor/cleanup/rollback ...），与 fnos 版同一套核心。

环境约定：
  · TRIM_PKGVAR = ~/Library/Application Support/RawArchiver（应用数据目录；
    任务态 .rawarchiver/ 写在这里，worker 子进程继承）
  · PyInstaller onedir 下 APP_DEST = Contents/Resources/（www/、scripts/、vendor/ 都在那）
"""

import os
import sys
import threading
import webbrowser

SELF = os.path.abspath(__file__)
APP_DEST = os.path.dirname(SELF)
SCRIPT = os.path.join(APP_DEST, "scripts", "raw_archiver.py")

GATEWAY_PREFIX = "/app/rawarchiver"
FROZEN = bool(getattr(sys, "frozen", False))


def _looks_like_gui_launch(argv):
    """macOS 老式 Finder 会传 -psn_0_123456（进程序号），视为 GUI 启动。"""
    return not argv or all(a.startswith("-psn_") for a in argv)


def run_cli(argv):
    sys.path.insert(0, os.path.dirname(SCRIPT))
    import raw_archiver
    sys.argv = [SCRIPT] + argv
    return raw_archiver.main()


def pick_folder(title):
    """macOS 系统目录选择框（NSOpenPanel）。在 pywebview 的 js_api 线程里调用。

    返回所选路径字符串；用户取消返回 None。
    """
    import webview
    win = getattr(Bridge, "_window", None)
    if win is None:
        return None
    try:
        r = win.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
    except Exception:
        return None
    if isinstance(r, (list, tuple)):
        r = r[0] if r else None
    if r and isinstance(r, str):
        return r
    if isinstance(r, list) and r:
        return str(r[0])
    return None


class Bridge:
    """暴露给前端 window.pywebview.api 的方法。"""

    _window = None

    def pick_folder(self, title="选择目录"):
        return pick_folder(title)

    def app_version(self):
        try:
            import server_mac
            return server_mac.VERSION
        except Exception:
            return "0"


def _init_state_dir():
    var = os.path.expanduser("~/Library/Application Support/RawArchiver")
    try:
        os.makedirs(var, exist_ok=True)
    except Exception:
        var = os.path.expanduser("~/.rawarchiver-var")
        os.makedirs(var, exist_ok=True)
    os.environ["TRIM_PKGVAR"] = var
    return var


def run_gui():
    var = _init_state_dir()
    sys.path.insert(0, APP_DEST)
    import server_mac

    srv, port = server_mac.make_server()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = "http://127.0.0.1:%d%s/?t=%s" % (port, GATEWAY_PREFIX, server_mac.TOKEN)
    server_mac.log("gui starting on 127.0.0.1:%d (var=%s)" % (port, var))

    # 把窗口 URL 落盘（调试 / CI 自测用；删掉不影响运行）
    try:
        with open(os.path.join(var, "gui.url"), "w", encoding="utf-8") as f:
            f.write(url)
    except Exception:
        pass

    used_fallback = False
    try:
        import webview
        Bridge._window = webview.create_window(
            "RAW 归档", url, js_api=Bridge(),
            width=1020, height=840, min_size=(720, 600))
        webview.start()  # 阻塞直到窗口关闭
    except Exception as e:
        # pywebview 不可用（缺依赖/无窗口环境）→ 默认浏览器兜底
        used_fallback = True
        msg = "原生窗口不可用（%s），已用默认浏览器打开: %s" % (e, url)
        try:
            print(msg, flush=True)
        except Exception:
            pass
        server_mac.log(msg)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    if used_fallback:
        # 浏览器模式下保持服务运行（关掉终端 / Ctrl+C 才退出）
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    else:
        # 窗口已关闭。若有归档任务在跑，worker 是独立子进程，
        # 会继续完成（日志与报告照写），这里不杀它。
        srv.shutdown()


def main():
    if "--gui" in sys.argv:
        run_gui()
        return 0
    argv = [a for a in sys.argv[1:] if a not in ("--gui",)]
    if _looks_like_gui_launch(argv):
        run_gui()
        return 0
    return run_cli(argv)


if __name__ == "__main__":
    sys.exit(main())
