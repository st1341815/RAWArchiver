#!/usr/bin/env python3
"""手机窄屏溢出检查（开发自检，不进发布包）。

为什么要用 iframe：chromium headless 的窗口最小只有 500px（--window-size=320
实际得到 innerWidth=500），320/340/360 这些真机宽度根本测不出来，媒体查询也不会
按窄屏生效。改成「外层页面 + 指定宽度的 iframe」后，iframe 内部的视口和媒体查询
都严格等于目标宽度，同源还能直接读取内部 DOM。

测量三处：
  1. 顶部 header —— 徽章 / 标题 / tab 是否挤出容器，或文字被压裁（scrollWidth > clientWidth）
  2. 「选项」区 #cardOpts —— 中文说明文字撑宽卡片
  3. 整页 —— 是否出现横向滚动

用法：
    python3 tools/mobile_overflow_check.py            # 默认 390 360 340 320
    python3 tools/mobile_overflow_check.py 414 375    # 指定宽度

依赖：系统 chromium（/usr/bin/chromium）+ python3 标准库。
源文件不会被修改：www 复制到临时目录后再测。
"""
import html
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WWW = ROOT / "fnos/rawarchiver/app/www"
CHROMIUM = "/usr/bin/chromium"

HARNESS = r"""<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:#fff}
iframe{display:block;border:0;background:#fff}
#__probe{white-space:pre-wrap;font:12px monospace;margin:0;padding:4px}</style>
<iframe id="f" src="www/index.html"></iframe>
<pre id="__probe">PENDING</pre>
<script>
var W = parseInt(new URLSearchParams(location.search).get('w') || '390', 10);
var f = document.getElementById('f');
f.style.width = W + 'px'; f.style.height = '2400px';

function collect() {
  var d = f.contentDocument, w = f.contentWindow;
  var co = d.getElementById('cardOpts');
  if (co) { co.hidden = false; co.removeAttribute('hidden'); }
  var res = { view: w.innerWidth,
              docOver: d.documentElement.scrollWidth - w.innerWidth,
              bodyBg: d.defaultView.getComputedStyle(d.body).backgroundColor,
              hdr: [], clipped: [], card: [], hdrW: null, cardW: null };

  var hdr = d.querySelector('.hdr-in');
  if (hdr) {
    var hb = hdr.getBoundingClientRect();
    res.hdrW = Math.round(hb.width);
    Array.prototype.forEach.call(hdr.querySelectorAll('*'), function (el) {
      if (!el.getClientRects().length) return;
      var r = el.getBoundingClientRect();
      if (r.right > hb.right + 0.5 || r.left < hb.left - 0.5) {
        res.hdr.push((el.id || el.className || el.tagName)
          + ' overR=' + Math.round(r.right - hb.right)
          + ' overL=' + Math.round(hb.left - r.left)
          + ' [' + (el.textContent || '').trim().slice(0, 14) + ']');
      }
    });
    Array.prototype.forEach.call(hdr.querySelectorAll('.tab, .dotdot, h1, h1 small'), function (el) {
      if (!el.getClientRects().length) return;
      if (el.scrollWidth > el.clientWidth + 1) {
        res.clipped.push((el.id || el.className || el.tagName)
          + ' scroll=' + el.scrollWidth + ' client=' + el.clientWidth
          + ' [' + (el.textContent || '').trim().slice(0, 14) + ']');
      }
    });
  }

  if (co) {
    var cb = co.getBoundingClientRect();
    res.cardW = Math.round(cb.width);
    Array.prototype.forEach.call(co.querySelectorAll('*'), function (el) {
      if (!el.getClientRects().length) return;
      var r = el.getBoundingClientRect();
      if (r.right > cb.right + 0.5) {
        res.card.push((el.className || el.tagName) + ' over=' + Math.round(r.right - cb.right)
          + ' [' + (el.textContent || '').trim().slice(0, 18) + ']');
      }
    });
  }
  return res;
}

f.addEventListener('load', function () {
  setTimeout(function () {
    var out;
    try { out = JSON.stringify(collect(), null, 1); }
    catch (e) { out = 'ERR ' + e.message; }
    document.getElementById('__probe').textContent = out;
  }, 900);
});
</script>
"""


def serve(www: Path):
    handler = partial(SimpleHTTPRequestHandler, directory=str(www))
    handler.log_message = lambda *a, **k: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def check_one(width: int) -> dict | str:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # index.html 用网关绝对路径引用样式（/app/rawarchiver/assets/ra.css），
        # 本地 http.server 若只挂 www 目录会 404，测出来的就是无样式的假结果。
        # 所以同时把 www 复制到 td/app/rawarchiver/，让绝对路径也能命中。
        www = root / "www"
        shutil.copytree(WWW, www)
        shutil.copytree(WWW, root / "app" / "rawarchiver")
        (root / "_harness.html").write_text(HARNESS)
        srv = serve(root)
        port = srv.server_address[1]
        try:
            time.sleep(0.5)
            out = subprocess.run(
                [CHROMIUM, "--headless=new", "--no-sandbox", "--disable-gpu",
                 "--hide-scrollbars", "--window-size=1200,2600",
                 "--virtual-time-budget=8000", "--dump-dom",
                 f"http://127.0.0.1:{port}/_harness.html?w={width}"],
                capture_output=True, text=True, timeout=120).stdout
            m = re.search(r'<pre id="__probe">(.*?)</pre>', out, re.S)
            if not m:
                return "PROBE NOT FOUND（chromium 是否可用？）"
            body = html.unescape(m.group(1))
            if body.startswith("ERR"):
                return body
            import json
            return json.loads(body)
        finally:
            srv.shutdown()


def main(widths):
    bad = 0
    for w in widths:
        r = check_one(w)
        if isinstance(r, str):
            print(f"===== {w}px =====  ERROR\n  {r}\n")
            bad += 1
            continue
        hdr_bad = len(r.get("hdr") or [])
        clip_bad = len(r.get("clipped") or [])
        card_bad = len(r.get("card") or [])
        doc_ok = r["docOver"] <= 0
        ok = hdr_bad == 0 and clip_bad == 0 and card_bad == 0 and doc_ok
        if not ok:
            bad += 1
        print(f"===== {w}px =====  {'PASS' if ok else 'FAIL'}")
        print(f"VIEW_W={r['view']}  HDR_W={r.get('hdrW')}  "
              f"DOC_OVERFLOW={r['docOver']}  CARD_W={r.get('cardW')}  BODY_BG={r.get('bodyBg')}")
        if r.get("bodyBg") in (None, "rgba(0, 0, 0, 0)", "rgb(255, 255, 255)"):
            print("  ⚠ 样式疑似未加载（body 背景仍为默认值），结果不可信")
            ok = False
        if r.get("hdr"):
            print("  HEADER 越界：" + " | ".join(r["hdr"]))
        if r.get("clipped"):
            print("  HEADER 文字被压：" + " | ".join(r["clipped"]))
        if r.get("card"):
            print("  选项区越界：" + " | ".join(r["card"][:6]))
        if ok:
            print("  顶部与选项区均无溢出")
        print()
    print("结论：" + ("全部通过" if bad == 0 else f"{bad} 个宽度存在问题，需要修"))
    return 1 if bad else 0


if __name__ == "__main__":
    ws = [int(a) for a in sys.argv[1:]] or [390, 360, 340, 320]
    sys.exit(main(ws))
