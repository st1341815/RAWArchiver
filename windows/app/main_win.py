#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAW 归档 —— Windows 应用入口。

两种运行方式：
  1. 无参数（双击 RawArchiver.exe）：起本地 HTTP 服务（server_win）+ pywebview 原生窗口。
     Windows 上 pywebview 用 EdgeChromium 后端（WebView2 运行时，Win11 自带）。
     目录选择走系统文件夹选择框（IFileDialog）。
  2. 带参数（终端 / server 子进程 worker）：原样转发给 scripts/raw_archiver.py 的 CLI。

环境约定：
  · TRIM_PKGVAR = %APPDATA%\\RawArchiver（任务态 .rawarchiver/ 写这里，worker 子进程继承）
  · PyInstaller onedir 下 APP_DEST = <dist>/RawArchiver/_internal/（www、scripts、vendor 都在那）
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
    return not argv


def run_cli(argv):
    sys.path.insert(0, os.path.dirname(SCRIPT))
    import raw_archiver
    sys.argv = [SCRIPT] + argv
    return raw_archiver.main()


class Bridge:
    """暴露给前端 window.pywebview.api 的方法。"""

    _window = None

    def pick_folder(self, title="选择目录"):
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
        if isinstance(r, str) and r:
            return r
        if isinstance(r, list) and r:
            return str(r[0])
        return None

    def app_version(self):
        try:
            import server_win
            return server_win.VERSION
        except Exception:
            return "0"


def _init_state_dir():
    var = os.environ.get("APPDATA") or os.path.expanduser("~")
    var = os.path.join(var, "RawArchiver")
    try:
        os.makedirs(var, exist_ok=True)
    except Exception:
        var = os.path.join(os.path.expanduser("~"), ".rawarchiver-var")
        os.makedirs(var, exist_ok=True)
    os.environ["TRIM_PKGVAR"] = var
    return var


def run_gui():
    var = _init_state_dir()
    sys.path.insert(0, APP_DEST)
    import server_win

    srv, port = server_win.make_server()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = "http://127.0.0.1:%d%s/?t=%s" % (port, GATEWAY_PREFIX, server_win.TOKEN)
    server_win.log("gui starting on 127.0.0.1:%d (var=%s)" % (port, var))

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
        webview.start()
    except Exception as e:
        used_fallback = True
        msg = "原生窗口不可用（%s），已用默认浏览器打开: %s" % (e, url)
        try:
            print(msg, flush=True)
        except Exception:
            pass
        server_win.log(msg)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    if used_fallback:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    else:
        srv.shutdown()


def main():
    if "--gui" in sys.argv:
        run_gui()
        return 0
    argv = [a for a in sys.argv[1:] if a != "--gui"]
    if _looks_like_gui_launch(argv):
        run_gui()
        return 0
    return run_cli(argv)


if __name__ == "__main__":
    sys.exit(main())
