#!/usr/bin/env python3
"""手机窄屏溢出检查（开发自检，不进发布包）。

把「选项」区（#cardOpts）宽度锁定为指定值，测量内部是否有元素越界，
用于防止「把说明文字塞进控件名 + nowrap」这类中文排版溢出复发。

用法：
    python3 tools/mobile_overflow_check.py            # 默认 390 360 340 320
    python3 tools/mobile_overflow_check.py 414 375     # 指定宽度

依赖：chromium（headless 即可）、python3 标准库。
原理：复制 www 到临时目录 → 注入测量探针 → http.server → chromium --dump-dom 取结果。
源文件不会被修改。
"""
import html
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WWW = ROOT / "fnos/rawarchiver/app/www"

PROBE = """
<script>
window.addEventListener('load', function(){
  setTimeout(function(){
    var W = parseInt(new URLSearchParams(location.search).get('w') || '390', 10);
    var co = document.getElementById('cardOpts');
    co.hidden = false; co.removeAttribute('hidden');
    co.style.width = W + 'px'; co.style.maxWidth = W + 'px'; co.style.boxSizing = 'border-box';
    var box = co.getBoundingClientRect(), over = [], chk = [], notes = [];
    co.querySelectorAll('*').forEach(function(el){
      if(!el.getClientRects().length) return;
      var r = el.getBoundingClientRect();
      if(r.right > box.right + 0.5){
        over.push(el.tagName + '.' + (el.className||'') + '[w=' + Math.round(r.width)
          + ',over=' + Math.round(r.right - box.right) + '] ' + (el.textContent||'').trim().slice(0,22));
      }
    });
    co.querySelectorAll('.chk').forEach(function(el){
      var r = el.getBoundingClientRect();
      chk.push((el.textContent||'').trim().slice(0,18) + '[w=' + Math.round(r.width) + ']');
    });
    co.querySelectorAll('.gnote').forEach(function(el){
      var r = el.getBoundingClientRect();
      notes.push('[h=' + Math.round(r.height) + '] ' + (el.textContent||'').trim().slice(0,36));
    });
    var p = document.createElement('pre'); p.id = '__probe';
    p.textContent = 'CARD_W=' + Math.round(box.width)
      + '\\nOVERFLOW=' + over.length + (over.length ? '\\n  ' + over.slice(0,8).join('\\n  ') : '')
      + '\\nCHK=' + chk.join(' | ')
      + '\\nNOTES=' + notes.join(' | ');
    document.body.appendChild(p);
  }, 800);
});
</script>
</body>"""


def check(width: int, port: int) -> str:
    with tempfile.TemporaryDirectory() as td:
        www = Path(td) / "www"
        shutil.copytree(WWW, www)
        p = www / "index.html"
        p.write_text(p.read_text().replace("</body>", PROBE, 1))
        srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port)],
                               cwd=str(www), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.8)
            out = subprocess.run(
                ["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                 "--window-size=800,2400", "--virtual-time-budget=5000", "--dump-dom",
                 f"http://127.0.0.1:{port}/index.html?w={width}"],
                capture_output=True, text=True, timeout=90).stdout
            m = re.search(r'<pre id="__probe">(.*?)</pre>', out, re.S)
            return html.unescape(m.group(1)) if m else "PROBE NOT FOUND（chromium 是否可用？）"
        finally:
            srv.terminate()


if __name__ == "__main__":
    widths = [int(a) for a in sys.argv[1:]] or [390, 360, 340, 320]
    bad = 0
    for i, w in enumerate(widths):
        r = check(w, 8900 + i)
        first = r.splitlines()[1] if len(r.splitlines()) > 1 else "?"
        if "OVERFLOW=0" not in first:
            bad += 1
        print(f"===== {w}px =====")
        print(r)
        print()
    print("结论：" + ("全部通过，无横向溢出" if bad == 0 else f"{bad} 个宽度存在溢出，需要修"))
    sys.exit(1 if bad else 0)
