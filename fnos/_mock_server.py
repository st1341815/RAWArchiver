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

# 联调路径当「可移动设备」用：让 /tmp/ra_mock_dev/* 命中 removable 前缀，
# 这样暂存 / move 清源 / 设备徽标等分支在浏览器里都能走到。
core.REMOVABLE_PFX = core.REMOVABLE_PFX + ('/tmp/ra_mock_dev/',)

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
            # 对齐生产网关的模式值：devices 识别条等网关专属交互要在本地联调里可见
            return self._json({'ok': True, 'mode': 'fnos-gateway', 'version': core.APP_VER})
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
            tid = b.get('taskId') or b.get('id') or ''   # 前端发的是 taskId（旧代码读 id，已对齐）
            try:
                st = core.load_state(tid)
            except Exception:
                st = None
            if not st:
                return self._json({'ok': False, 'error': '任务不存在'})
            st['logs'] = st.get('logs', [])[-80:]
            st.pop('done', None)
            st.pop('to_delete', None)
            return self._json({'ok': True, 'state': st})
        if act == 'devices':
            import glob as _g
            lst = []
            for d in sorted(_g.glob('/tmp/ra_mock_dev/*')):
                if os.path.isdir(d):
                    n = sum(1 for _r, _d, fs_ in os.walk(d) for f in fs_
                            if os.path.splitext(f)[1].lower() in core.ALL_EXTS)
                    lst.append({'path': d, 'label': os.path.basename(d), 'files': n})
            return self._json({'ok': True, 'list': lst})
        if act == 'doctor':
            return self._json({'ok': True, 'result': {
                'app': core.APP_NAME, 'version': core.APP_VER, 'python': sys.version.split()[0],
                'exifread': bool(getattr(core, 'exifread', None)),
                'pillow': bool(getattr(core, 'Image', None)),
                'exiftool': core._exiftool_bin(), 'ledger': core.ledger_path(),
                'perl': os.path.exists('/usr/bin/perl')}})
        if act == 'browse':
            p = os.path.abspath((b.get('path') or '/').strip() or '/')
            if not os.path.isdir(p):
                return self._json({'ok': False, 'error': '不是目录: %s' % p})
            dirs = []
            try:
                for c in sorted(os.listdir(p)):
                    if c.startswith('.'):
                        continue
                    fp = os.path.join(p, c)
                    if os.path.isdir(fp):
                        dirs.append({'name': c, 'path': fp})
            except OSError as e:
                return self._json({'ok': False, 'error': str(e)})
            parent = os.path.dirname(p) if p != '/' else None
            return self._json({'ok': True, 'path': p, 'parent': parent,
                               'writable': os.access(p, os.W_OK), 'dirs': dirs})
        if act == 'cancel':
            from pathlib import Path as _P
            try:
                d = _P(core.task_dir(b.get('taskId') or ''))
                d.mkdir(parents=True, exist_ok=True)
                (d / 'cancel').write_text('1', encoding='utf-8')
                return self._json({'ok': True})
            except Exception as e:
                return self._json({'ok': False, 'error': str(e)})
        if act == 'cleanup':
            try:
                r = core.do_cleanup(out, b.get('taskId') or '')
            except Exception as e:
                return self._json({'ok': False, 'error': str(e)})
            r.setdefault('ok', True)
            return self._json(r)
        if act == 'rollback':
            try:
                r = core.do_rollback(out, b.get('taskId') or '')
            except Exception as e:
                return self._json({'ok': False, 'error': str(e)})
            r.setdefault('ok', True)
            return self._json(r)
        if act == 'ledger':
            if (b.get('op') or 'stats') != 'stats':
                return self._json({'ok': False, 'error': 'mock 只实现 stats'})
            return self._json(core.ledger_stats(out or None))
        return self._json({'ok': False, 'error': 'mock 未实现: ' + act})


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
    print('serving on http://127.0.0.1:%d/app/rawarchiver/' % port, flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
