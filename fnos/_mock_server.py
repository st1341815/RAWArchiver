#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 UI 联调用的 mock 服务（不属于发布包）。

把 fnos/rawarchiver/app/www 映射到 /app/rawarchiver/ 前缀，并用**真实的** core 处理
preview / start / status，从而在浏览器里验证前端（含重复归档确认门）。

用法：
    PYTHONPATH= python3 fnos/_mock_server.py [端口]
"""
import io
import json
import os
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, 'rawarchiver', 'app')
WWW = os.path.join(APP, 'www')
CORE = os.path.join(APP, 'scripts', 'raw_archiver.py')

os.environ.setdefault('TRIM_PKGVAR', tempfile.mkdtemp(prefix='ra_mock_var_'))
sys.path.insert(0, os.path.dirname(CORE))
import raw_archiver as core  # noqa: E402

# 联调用：假图没有 EXIF，给个固定拍摄日期，便于验证「已归档 / 冲突」等分支
if os.environ.get('RA_MOCK_FIXED_DATE', '1') == '1':
    from datetime import datetime
    core.resolve_date = lambda p: (datetime(2026, 1, 1, 9, 0, 0), 'exif')
    # v1.0.21 起：exifread/Pillow 都不可用时照片会改走 exiftool 批量（不经过 resolve_date），
    # 上面这个桩就失效了。联调要的是「每个文件都有日期」，所以强制走纯 Python 逐文件路径。
    core._PY_FAST = True

TASKS = {}
MIME = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8',
        '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml'}


def opts(b):
    return {'brand_folder': bool(b.get('brandFolder')),
            'handle_jpg': b.get('handleJpg') is not False,
            'handle_video': b.get('handleVideo') is not False,
            'month_dir': bool(b.get('monthDir')),
            'staging': bool(b.get('staging', True)),
            'mode': b.get('mode', 'copy'),
            'dup_policy': b.get('dupPolicy') or 'skip',
            'dup_hash': 'full' if b.get('dupHash') == 'full' else 'sampled',
            'dup_guard': b.get('dupGuard') or ''}


def run_bg(src, out, o, tid):
    buf = io.StringIO()
    with redirect_stdout(buf):
        core.run_task(src, out, o, tid)


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _static(self, path):
        rel = path[len('/app/rawarchiver/'):] or 'index.html'
        fp = os.path.join(WWW, rel)
        if not os.path.isfile(fp):
            self._json({'ok': False, 'error': 'not found: ' + rel}, 404)
            return
        b = open(fp, 'rb').read()
        self.send_response(200)
        self.send_header('Content-Type', MIME.get(os.path.splitext(fp)[1], 'application/octet-stream'))
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urlparse(self.path).path
        if p.startswith('/app/rawarchiver/'):
            return self._static(p)
        self._json({'ok': False}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        try:
            b = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            b = {}
        act = b.get('action') or (parse_qs(u.query).get('action') or ['info'])[0]
        out = (b.get('output') or '').strip()
        if act == 'info':
            return self._json({'ok': True, 'mode': 'mock', 'version': core.APP_VER})
        if act == 'preview':
            return self._json({'ok': True, 'result': core.do_preview(
                b['source'], opts(b), output=out)})
        if act == 'start':
            o = opts(b)
            if o['dup_policy'] == 'force':
                okg, errg = core.check_guard(o['dup_guard'], b['source'], out, o)
                if not okg:
                    return self._json({'ok': False, 'code': 'need_confirm', 'error': errg})
            tid = b.get('taskId') or 'M%d' % int(time.time() * 1000)
            threading.Thread(target=run_bg, args=(b['source'], out, o, tid), daemon=True).start()
            return self._json({'ok': True, 'taskId': tid})
        if act == 'status':
            st = core.load_state(b.get('id', ''))
            if not st:
                return self._json({'ok': False, 'error': '任务不存在'})
            st['logs'] = st.get('logs', [])[-80:]
            st.pop('done', None)
            st.pop('to_delete', None)
            return self._json({'ok': True, 'state': st})
        return self._json({'ok': False, 'error': 'mock 未实现: ' + act})


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
    print('serving on http://127.0.0.1:%d/app/rawarchiver/' % port, flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
