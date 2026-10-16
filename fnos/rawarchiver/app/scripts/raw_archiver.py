#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAW 归档 —— 核心处理脚本 v1.0.0
源：U盘/SD/TF卡（只读，move 模式归档后清源）或本地目录
输出：用户指定的任意 NAS 目录（只落归档文件 + log/）

盘面约定（v1.0.14 起）：
  · 任务状态（state.json / cancel / 暂存）写「应用运行的主目录」——$TRIM_PKGVAR/.rawarchiver/
    （fnOS 应用数据目录），不进用户输出目录；
  · 运行日志与下游报告写「输出目录/log/」；
  · 源目录只读，任何情况下不产生文件或文件夹。
"""
import os
import sys
import json
import time
import shutil
import argparse
import subprocess
import hashlib
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import re

try:
    import exifread
except Exception:
    exifread = None
try:
    from PIL import Image
except Exception:
    Image = None

APP_NAME = 'RAW 归档'
APP_DIR  = '.rawarchiver'          # 状态目录名（落在应用运行的主目录下，不写用户输出目录）
LOG_DIR  = 'log'                   # 输出目录下存放运行日志与报告的文件夹
APP_VER  = '1.0.0'

RAW_EXTS = {'.nef','.nrw','.cr2','.cr3','.crw','.arw','.srf','.sr2','.raf','.orf','.dng','.pef','.rw2'}
JPG_EXTS = {'.jpg','.jpeg'}
VID_EXTS = {'.mp4','.mov','.mts','.m2ts','.avi','.mkv','.3gp','.mpg','.mpeg','.wmv','.flv','.m4v','.ts','.mod','.mxf'}
ALL_EXTS = RAW_EXTS | JPG_EXTS | VID_EXTS

DATE_DIR_RE   = re.compile(r'^\d{8}$')
SKIP_DIRS     = {'@eaDir', APP_DIR, '_inbox', '_exports', '_trash', '_restored',
                 'Thumbs.db', '.DS_Store', 'lost+found'}
REMOVABLE_PFX = ('/volumeUSB', '/mnt/usb', '/media/', '/run/media/', '/Volumes/', '/mediausb')

BRAND_MAP = {
    'NIKON':'Nikon','CANON':'Canon','SONY':'Sony','OLYMPUS':'Olympus','OM DIGITAL SOLUTIONS':'Olympus',
    'PANASONIC':'Panasonic','FUJIFILM':'Fujifilm','PENTAX':'Pentax','RICOH':'Pentax','SIGMA':'Sigma',
    'LEICA':'Leica','HASSELBLAD':'Hasselblad','PHASE ONE':'PhaseOne','SAMSUNG':'Samsung',
    'GOPRO':'GoPro','DJI':'DJI','APPLE':'Apple','HUAWEI':'Huawei','XIAOMI':'Xiaomi',
}

# ======================== 工具 ========================

def now():
    return time.time()

def atomic_write(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp.%d' % (time.time() * 1e6 % 1e6))
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)

def log_msg(st, msg):
    st.setdefault('logs', []).append({'t': datetime.now().strftime('%H:%M:%S'), 'msg': msg})
    if len(st['logs']) > 2000:
        st['logs'] = st['logs'][-1500:]
    print(msg, flush=True)

# ---- 源类型判定 ----

def is_removable(path):
    if not path:
        return False
    p = os.path.realpath(os.path.abspath(path))
    if any(p.startswith(x) for x in REMOVABLE_PFX):
        return True
    try:
        with open('/proc/mounts', encoding='utf-8', errors='ignore') as f:
            for ln in f:
                parts = ln.split()
                if len(parts) >= 2 and p.startswith(parts[1]):
                    return any(k in ln for k in ('usb', 'udisks', 'shortname=', 'vfat', 'exfat', 'fuseblk'))
    except Exception:
        pass
    return False

def source_info(path):
    p = os.path.abspath(path)
    ok = os.path.isdir(p)
    total, free, cnt = 0, 0, 0
    if ok:
        try:
            st = os.statvfs(p)
            LIMIT = 1 << 55
            for attr, key in (('f_blocks', 'total'), ('f_bavail', 'free')):
                v = getattr(st, attr, 0) * max(st.f_frsize or st.f_bsize or 0, 0)
                if v < 0 or v > LIMIT:
                    v = 0
                if key == 'total':
                    total = v
                else:
                    free = v
        except Exception:
            pass
        try:
            cnt = sum(1 for _ in scan_images(p, {'handle_jpg': True, 'handle_video': True}, limit=2000))
        except Exception:
            cnt = -1
    return {'path': p, 'ok': ok, 'removable': is_removable(p),
            'total_bytes': total, 'free_bytes': free, 'sample_count': cnt,
            'app': APP_NAME, 'version': APP_VER}

def path_inside(child, parent):
    if not child or not parent:
        return False
    c, p = os.path.realpath(os.path.abspath(child)), os.path.realpath(os.path.abspath(parent))
    return c == p or c.startswith(p + os.sep)

# ---- ExifTool 定位（三级：env → 随包 → 系统 PATH）----

_ET_BIN = None
_ET_PERL = None

def _et_candidates():
    base = Path(__file__).resolve().parent.parent
    cands = []
    envp = os.environ.get('EXIFTOOL_PATH')
    if envp:
        cands.append(envp)
    for rel in ('vendor/exiftool/exiftool', 'app/exiftool/exiftool',
                'thirdparty/exiftool/Image-ExifTool-13.00/exiftool'):
        cands.append(str(base / rel))
    for rel in ('exiftool', 'exiftool_files/exiftool'):
        cands.append(str(base.parent / rel))
    if sys.platform == 'win32':
        cands += ['exiftool.exe', str(base / 'vendor' / 'exiftool' / 'exiftool.exe')]
    cands.append('exiftool')
    return [c for c in cands if c]

def _et_run_prefix(binp):
    """返回调用前缀：.exe 直接执行，perl 脚本走 perl"""
    s = str(binp).lower()
    if s.endswith('.exe'):
        return [str(binp)]
    if os.path.basename(s) in ('exiftool',) and os.path.exists('/usr/bin/perl'):
        return ['perl', str(binp)]
    if os.path.basename(s) in ('exiftool',):
        return [str(binp)]
    return [str(binp)]

def _exiftool_bin():
    global _ET_BIN
    if _ET_BIN is not None:
        return _ET_BIN
    for c in _et_candidates():
        try:
            r = subprocess.run(_et_run_prefix(c) + ['-ver'], capture_output=True, text=True, timeout=8)
            if r.returncode == 0 and r.stdout.strip():
                _ET_BIN = c
                return c
        except Exception:
            continue
    _ET_BIN = False
    return False

def et_available():
    return bool(_exiftool_bin())

# ---- 日期解析（纯读，不动文件）----

def _parse_dt(v):
    if v is None:
        return None
    s = str(v).strip()
    for fmt in ('%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y:%m:%d', '%Y-%m-%d'):
        try:
            return datetime.strptime(s[:19], fmt)
        except Exception:
            pass
    try:
        n = float(s)
        if n > 1e9:
            return datetime.fromtimestamp(n)
    except Exception:
        pass
    return None

def _norm_make(m):
    if not m:
        return None
    s = str(m).strip()
    return BRAND_MAP.get(s.upper(), s)

def _get_make(path):
    if exifread:
        try:
            with open(path, 'rb') as f:
                t = exifread.process_file(f, details=False, stop_tag='Image Make')
            m = t.get('Image Make')
            if m:
                return _norm_make(m)
        except Exception:
            pass
    binp = _exiftool_bin()
    if binp:
        try:
            r = subprocess.run(_et_run_prefix(binp) + ['-j', '-Make', path],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout:
                o = json.loads(r.stdout)[0]
                return _norm_make(o.get('Make') or o.get('System:Make'))
        except Exception:
            pass
    return None

def resolve_date(path):
    """返回 (datetime|None, tag)。照片取不到 EXIF → (None,'unknown')；视频兜底 file_mtime。"""
    ext = os.path.splitext(path)[1].lower()
    video = ext in VID_EXTS

    if exifread and not video:
        try:
            with open(path, 'rb') as f:
                tags = exifread.process_file(f, details=False, stop_tag='DateTimeOriginal')
            for k in ('EXIF DateTimeOriginal', 'EXIF DateTimeDigitized', 'Image DateTime'):
                v = tags.get(k)
                if v:
                    dt = _parse_dt(v)
                    if dt:
                        return dt, 'exifread'
        except Exception:
            pass

    if Image and ext in JPG_EXTS:
        try:
            im = Image.open(path)
            im.load()
            ex = im._getexif()
            if isinstance(ex, dict):
                for k in (0x9003, 0x9004, 0x0132):
                    v = ex.get(k)
                    if v:
                        dt = _parse_dt(v)
                        if dt:
                            return dt, 'pillow'
        except Exception:
            pass

    binp = _exiftool_bin()
    if binp:
        try:
            et_tags = ['-CreateDate', '-DateTimeOriginal', '-MediaCreateDate', '-TrackCreateDate']
            et_keys = ('ExifIFD:CreateDate', 'ExifIFD:DateTimeOriginal',
                       'QuickTime:CreateDate', 'QuickTime:MediaCreateDate')
            if video:
                # 红线：文件修改时间兜底只允许用于视频，照片无 EXIF 视为 unknown 并跳过
                et_tags.append('-FileModifyDate')
                et_keys += ('System:FileModifyDate',)
            cmd = _et_run_prefix(binp) + ['-j', '-G1', '-n', '-m'] + et_tags + [path]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout:
                for o in json.loads(r.stdout):
                    for k in et_keys:
                        v = o.get(k)
                        if v:
                            dt = _parse_dt(v)
                            if dt:
                                return dt, k.split(':')[0].lower()
        except Exception:
            pass

    if video:
        try:
            return datetime.fromtimestamp(os.path.getmtime(path)), 'file_mtime'
        except Exception:
            pass
    return None, 'unknown'

# ---- 扫描 ----

def scan_images(root, opts, limit=None):
    root = os.path.abspath(root)
    cnt = 0
    for dn, dns, fns in os.walk(root, topdown=True, followlinks=False):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not DATE_DIR_RE.match(d)]
        dns.sort()
        for fn in sorted(fns):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in ALL_EXTS:
                continue
            if ext in JPG_EXTS and not opts.get('handle_jpg', True):
                continue
            if ext in VID_EXTS and not opts.get('handle_video', True):
                continue
            yield os.path.join(dn, fn)
            cnt += 1
            if limit and cnt >= limit:
                return

# ---- 目标路径 ----

def build_target(rel_src, dt, opts, reserved, output):
    base_name = os.path.splitext(os.path.basename(rel_src))[0]
    ext = os.path.splitext(rel_src)[1].lower()
    date_str = dt.strftime('%Y%m%d') if dt else 'NoDate'
    ymd_dir = date_str if dt else '_NoDate'

    folder = ymd_dir
    if opts.get('brand_folder'):
        mk = opts.get('_maker_cache', {}).get(rel_src)
        if mk:
            folder = os.path.join(mk, ymd_dir)

    new_name = '%s_%s%s' % (base_name, date_str, ext)
    dst = os.path.join(output, folder, new_name)

    base, n = dst, 1
    while dst in reserved or os.path.exists(dst):
        dst = '%s_%d%s' % (os.path.splitext(base)[0], n, ext)
        n += 1
    reserved.add(dst)

    month_dst = None
    if opts.get('month_dir') and dt and ext in (JPG_EXTS | VID_EXTS):
        md = dt.strftime('%m')
        mpath = os.path.join(output, md, new_name)
        mb, mn = mpath, 1
        while mpath in reserved or os.path.exists(mpath):
            mpath = '%s_%d%s' % (os.path.splitext(mb)[0], mn, ext)
            mn += 1
        reserved.add(mpath)
        month_dst = mpath
    return dst, month_dst

# ---- 预览 ----

def do_preview(source, opts, limit=500):
    source = os.path.abspath(source)
    rows, maker_cache = [], {}
    by_type, bad_count, conflicts = defaultdict(int), 0, 0
    reserved = set()
    total_size = 0
    for fp in scan_images(source, opts):
        try:
            sz = os.path.getsize(fp)
        except Exception:
            continue
        total_size += sz
        ext = os.path.splitext(fp)[1].lower()
        by_type[ext] += 1
        rel = os.path.relpath(fp, source)
        dt, tag = resolve_date(fp)
        if tag in ('file_mtime', 'unknown'):
            bad_count += 1
        if opts.get('brand_folder'):
            maker_cache[rel] = _get_make(fp)
        opts['_maker_cache'] = maker_cache
        dst, _md = build_target(rel, dt, opts, reserved, source)
        # build_target 已就地消解重名（_1/_2），返回的 dst 必唯一；改用“无冲突目标名”判断本文件是否被加后缀
        clean_dst, _ = build_target(rel, dt, opts, set(), source)
        if clean_dst != dst:
            conflicts += 1
        rows.append({'src': rel, 'size': sz,
                     'date': dt.strftime('%Y-%m-%d') if dt else None,
                     'date_from': tag,
                     'dst_rel': os.path.relpath(dst, source) if dst else None,
                     'bad': tag in ('file_mtime', 'unknown'),
                     'skip': (ext in (RAW_EXTS | JPG_EXTS) and tag == 'unknown')})
        if limit and len(rows) >= limit:
            break
    dates = sorted({r['date'] for r in rows if r['date']})
    return {'source': source, 'removable': is_removable(source),
            'total': len(rows), 'size': total_size, 'by_type': dict(by_type),
            'date_range': [dates[0], dates[-1]] if dates else [None, None],
            'bad_count': bad_count, 'conflicts': conflicts,
            'raw_skip_hint': sum(1 for r in rows if r['skip']),
            'removable_note': 'move 模式归档成功后将清空源设备' if is_removable(source) else '',
            'exiftool': et_available(),
            'sample': rows[:limit]}

# ---- 任务态 / 日志 路径 ----
#
# 状态目录「应用运行的主目录」：
#   fnOS 包 → $TRIM_PKGVAR/.rawarchiver（fnOS 注入的应用数据目录，如 /vol2/@appdata/rawarchiver）
#   CLI/本地 → <应用根>/.rawarchiver（应用根 = 本脚本上一级目录）
# 日志目录：<输出目录>/log/（运行日志 rawarchiver_<taskId>.log + 报告 _report_<taskId>.json）

def state_root():
    var = os.environ.get('TRIM_PKGVAR')
    if var:
        return os.path.join(var, APP_DIR)
    return str(Path(__file__).resolve().parent.parent / APP_DIR)

def task_dir(task_id, output=None):
    """任务状态目录（output 形参仅为兼容旧调用保留，已不再使用）。"""
    return os.path.join(state_root(), 'tasks', task_id)

def log_dir(output):
    return os.path.join(os.path.abspath(output), LOG_DIR)

def log_path(output, task_id):
    return os.path.join(log_dir(output), 'rawarchiver_%s.log' % task_id)

def report_path(output, task_id):
    return os.path.join(log_dir(output), '_report_%s.json' % task_id)

def load_state(tid, output=None):
    p = Path(task_dir(tid, output)) / 'state.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None

def cancelled(tid, output=None):
    return (Path(task_dir(tid, output)) / 'cancel').exists()

# ---- 内部暂存 ----

def tree_copy(src, dst, log_cb=None):
    os.makedirs(dst, exist_ok=True)
    n, b = 0, 0
    for fp in scan_images(src, {'handle_jpg': True, 'handle_video': True}):
        rel = os.path.relpath(fp, src)
        tp = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        shutil.copy2(fp, tp)
        n += 1
        b += os.path.getsize(tp)
        if log_cb and n % 50 == 0:
            log_cb('  暂存 %d 个文件 / %d MB' % (n, b >> 20))
    return n, b

# ---- 清源 ----

def do_cleanup(output, task_id, verify_hash=False):
    td = task_dir(task_id, output)
    sp = Path(td) / 'state.json'
    if not sp.exists():
        return {'ok': False, 'error': 'state.json 不存在，无法定位源'}
    st = json.loads(sp.read_text(encoding='utf-8'))
    src = st.get('source')
    if not src or not os.path.isdir(src):
        return {'ok': False, 'error': '源不可访问: %s（可能已拔卡或挂载点变化）' % src}
    ok, kept, fail = 0, [], []
    for it in st.get('to_delete', []):
        p = os.path.join(src, it['src'])
        try:
            if not os.path.isfile(p):
                ok += 1
                continue
            if os.path.getsize(p) != it['size']:
                kept.append(it['src'])
                continue
            if verify_hash and it.get('md5'):
                h = hashlib.md5()
                with open(p, 'rb') as f:
                    for chunk in iter(lambda: f.read(1 << 16), b''):
                        h.update(chunk)
                if h.hexdigest() != it['md5']:
                    kept.append(it['src'])
                    continue
            os.unlink(p)
            ok += 1
        except Exception as e:
            fail.append('%s: %s' % (it['src'], e))
    for root, dirs, _ in os.walk(src, topdown=False):
        for d in dirs:
            dp = os.path.join(root, d)
            try:
                if d.lower() != '@eadir' and not os.listdir(dp):
                    os.rmdir(dp)
            except Exception:
                pass
    return {'ok': True, 'deleted': ok, 'kept': kept, 'fail': fail}

# ---- 回滚（仅 copy 模式 + 本地源有效）----

def do_rollback(output, task_id):
    td = task_dir(task_id, output)
    sp = Path(td) / 'state.json'
    if not sp.exists():
        return {'ok': False, 'error': 'state.json 不存在'}
    st = json.loads(sp.read_text(encoding='utf-8'))
    if st.get('mode') == 'move' and st.get('removable'):
        return {'ok': False, 'error': '可移动介质已清源，无法回滚，请依靠 <输出目录>/log/ 下的 _report_*.json 清单'}
    moved, n = os.path.join(output, '_restored', st.get('id', task_id)), 0
    for it in st.get('done', []):
        if it.get('status') != 'ok':
            continue
        d = os.path.join(output, it['dst'])
        if not os.path.isfile(d):
            continue
        tp = os.path.join(moved, it['dst'])
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        shutil.move(d, tp)
        n += 1
    st['status'] = 'rolled_back'
    atomic_write(sp, st)
    return {'ok': True, 'restored': n, 'to': moved}

# ---- 主流程 ----

def run_task(source, output, opts, task_id):
    source = os.path.abspath(source)
    output = os.path.abspath(output)
    removable = is_removable(source)
    mode = opts.get('mode') or 'copy'
    opts['mode'] = mode

    td = task_dir(task_id, output)
    os.makedirs(td, exist_ok=True)
    sp = Path(td) / 'state.json'

    st = load_state(task_id, output)
    if not st:
        st = {'id': task_id, 'app': APP_NAME, 'version': APP_VER,
              'source': source, 'output': output, 'mode': mode, 'removable': removable,
              'brand_folder': bool(opts.get('brand_folder')),
              'handle_jpg': bool(opts.get('handle_jpg', True)),
              'handle_video': bool(opts.get('handle_video', True)),
              'month_dir': bool(opts.get('month_dir')), 'staging': bool(opts.get('staging', True)),
              'total': 0, 'current': 0, 'success': 0, 'failed': 0, 'skipped': 0,
              'status': 'pending', 'error': '', 'logs': [], 'done': [], 'to_delete': [],
              'created_at': now(), 'updated_at': now(), 'finished_at': None}
        atomic_write(sp, st)
    else:
        st['status'] = 'resuming'
        atomic_write(sp, st)

    def save():
        st['updated_at'] = now()
        atomic_write(sp, st)

    stage = None
    try:
        src = source
        if opts.get('staging', True) and removable:
            stage = os.path.join(td, 'stage')
            log_msg(st, '[暂存] 开始顺序复制到 NAS ...')
            t0 = now()
            n, b = tree_copy(src, stage, lambda m: log_msg(st, m))
            log_msg(st, '[暂存] 完成 %d 个文件 / %d MB，耗时 %ds' % (n, b >> 20, int(now() - t0)))
            src = stage

        log_msg(st, '模式: %s | 源为可移动介质: %s | 暂存: %s | ExifTool: %s'
                % (mode, removable, bool(stage), et_available()))
        st['status'] = 'running'
        save()

        reserved = set()
        done_key = {(it['src'], it['size']) for it in st.get('done', [])}
        st['skipped'] = 0
        st['failed'] = 0
        items = list(scan_images(src, opts))
        st['total'] = len(items)
        save()
        log_msg(st, '待处理 %d 个文件' % len(items))

        maker_cache = {}
        if opts.get('brand_folder'):
            log_msg(st, '正在识别品牌（仅本次）...')
            for fp in items:
                maker_cache[os.path.relpath(fp, src)] = _get_make(fp)
        opts['_maker_cache'] = maker_cache

        for idx, fp in enumerate(items, 1):
            if cancelled(task_id, output):
                st['status'] = 'cancelled'
                log_msg(st, '已取消')
                break
            st['current'] = idx
            save()
            rel = os.path.relpath(fp, src)
            ext = os.path.splitext(fp)[1].lower()
            try:
                sz = os.path.getsize(fp)
            except Exception:
                sz = 0
            key = (rel, sz)
            if key in done_key:
                st['skipped'] += 1
                continue
            dt, tag = resolve_date(fp)
            if dt is None:
                st['skipped'] += 1
                done_key.add(key)
                st['done'].append({'src': rel, 'size': sz, 'status': 'skip', 'reason': 'no_date'})
                st['logs'].append({'t': datetime.now().strftime('%H:%M:%S'),
                                   'status': 'skip', 'src': rel, 'msg': '无拍摄日期，跳过'})
                save()
                continue
            dst, mdst = build_target(rel, dt, opts, reserved, output)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if mode == 'move' and not removable and not stage:
                    shutil.move(fp, dst)
                else:
                    shutil.copy2(fp, dst)
                if mdst:
                    os.makedirs(os.path.dirname(mdst), exist_ok=True)
                    shutil.copy2(dst, mdst)
                st['success'] += 1
                done_key.add(key)
                ent = {'src': rel, 'size': sz, 'dst': os.path.relpath(dst, output),
                       'date': dt.strftime('%Y-%m-%d'), 'date_from': tag, 'status': 'ok'}
                if mdst:
                    ent['month_dst'] = os.path.relpath(mdst, output)
                st['done'].append(ent)
                if mode == 'move':
                    st['to_delete'].append({'src': rel, 'size': sz})
                st['logs'].append({'t': datetime.now().strftime('%H:%M:%S'), 'status': 'ok',
                                   'src': rel, 'dst': ent['dst'], 'date': ent['date'], 'from': tag})
            except Exception as e:
                st['failed'] += 1
                st['logs'].append({'t': datetime.now().strftime('%H:%M:%S'),
                                   'status': 'fail', 'src': rel, 'msg': str(e)})
            save()

        if mode == 'move' and removable and st['to_delete']:
            log_msg(st, '[清源] 归档成功，开始清空源设备上对应文件 ...')
            r = do_cleanup(output, task_id)
            if r.get('ok'):
                msg = '[清源] 已删除 %d 个文件' % r['deleted']
                if r['kept']:
                    msg += '，%d 个因大小校验未过而保留' % len(r['kept'])
                log_msg(st, msg)
                if r['fail']:
                    log_msg(st, '[清源] 失败: ' + '; '.join(r['fail'][:5]))
            else:
                log_msg(st, '[清源] 跳过（文件已安全归档）: %s，后续可用 --cleanup 补清' % r.get('error'))

        if st['status'] != 'cancelled':
            st['status'] = 'done'
        st['finished_at'] = now()
        log_msg(st, '完成: 成功 %d / 失败 %d / 跳过 %d' % (st['success'], st['failed'], st['skipped']))
        save()
        write_report(output, task_id, st)
    except Exception as e:
        st['status'] = 'error'
        st['error'] = str(e)
        st['logs'].append({'t': datetime.now().strftime('%H:%M:%S'),
                           'status': 'fail', 'msg': '异常: %s' % e})
        st['finished_at'] = now()
        save()
        raise
    finally:
        if stage and os.path.isdir(stage):
            shutil.rmtree(stage, ignore_errors=True)
            log_msg(st, '[暂存] 临时目录已清理')
            save()
    return st

def write_report(output, task_id, st):
    rp = report_path(output, task_id)
    atomic_write(rp, {
        'app': APP_NAME, 'version': APP_VER,
        'task_id': task_id, 'source': st['source'], 'output': st['output'],
        'removable': st['removable'], 'mode': st['mode'],
        'total': st['total'], 'success': st['success'],
        'failed': st['failed'], 'skipped': st['skipped'],
        'items': [d for d in st.get('done', []) if d.get('status') == 'ok'],
        'finished_at': datetime.fromtimestamp(st['finished_at']).isoformat() if st.get('finished_at') else None,
    })

# ---- CLI ----

def main():
    ap = argparse.ArgumentParser(description='%s v%s' % (APP_NAME, APP_VER))
    ap.add_argument('source', nargs='?', help='源目录（卡/U盘/本地目录）')
    ap.add_argument('--output', '-o', help='输出目录（归档落点）')
    ap.add_argument('--task-id', default=None, help='任务ID（续跑用）')
    ap.add_argument('--mode', choices=['copy', 'move'], default='copy', help='copy=留源, move=归档后清源')
    ap.add_argument('--preview', action='store_true', help='只预览不写盘，输出 JSON')
    ap.add_argument('--info', action='store_true', help='打印源信息 JSON')
    ap.add_argument('--doctor', action='store_true', help='自检依赖与 ExifTool')
    ap.add_argument('--cleanup', action='store_true', help='补清源')
    ap.add_argument('--rollback', action='store_true', help='回滚（仅 copy 模式）')
    ap.add_argument('--verify-hash', action='store_true', help='清源时做 MD5 校验（慢）')
    ap.add_argument('--staging', dest='staging', action='store_true', default=True)
    ap.add_argument('--no-staging', dest='staging', action='store_false')
    ap.add_argument('--brand', dest='brand_folder', action='store_true')
    ap.add_argument('--no-jpg', dest='handle_jpg', action='store_false', default=True)
    ap.add_argument('--no-video', dest='handle_video', action='store_false', default=True)
    ap.add_argument('--month', dest='month_dir', action='store_true')
    args = ap.parse_args()

    opts = {'brand_folder': args.brand_folder, 'handle_jpg': args.handle_jpg,
            'handle_video': args.handle_video, 'month_dir': args.month_dir,
            'staging': args.staging, 'mode': args.mode}

    if args.doctor:
        print(json.dumps({'app': APP_NAME, 'version': APP_VER,
                          'python': sys.version.split()[0],
                          'exifread': bool(exifread), 'pillow': bool(Image),
                          'exiftool': _exiftool_bin() or None,
                          'perl': os.path.exists('/usr/bin/perl')}, ensure_ascii=False))
        return 0
    if args.info:
        print(json.dumps(source_info(args.source), ensure_ascii=False))
        return 0
    if args.rollback:
        if not args.output or not args.task_id:
            print(json.dumps({'ok': False, 'error': '--rollback 需 --output 与 --task-id'}), file=sys.stderr)
            return 1
        print(json.dumps(do_rollback(args.output, args.task_id), ensure_ascii=False))
        return 0
    if args.preview:
        out = args.output or '/tmp/preview'
        print(json.dumps(do_preview(args.source, opts), ensure_ascii=False))
        return 0
    if args.cleanup:
        if not args.output or not args.task_id:
            print(json.dumps({'ok': False, 'error': '--cleanup 需 --output 与 --task-id'}), file=sys.stderr)
            return 1
        print(json.dumps(do_cleanup(args.output, args.task_id, args.verify_hash), ensure_ascii=False))
        return 0
    if not args.source:
        print(json.dumps({'ok': False, 'error': '缺少 source'}), file=sys.stderr)
        return 1
    if not args.output:
        print(json.dumps({'ok': False, 'error': '--output 必填'}), file=sys.stderr)
        return 1
    if path_inside(args.output, args.source):
        print(json.dumps({'ok': False, 'error': '输出目录不能位于源目录内部'}), file=sys.stderr)
        return 1
    if not os.path.isdir(args.source):
        print(json.dumps({'ok': False, 'error': '源不存在: %s' % args.source}), file=sys.stderr)
        return 1
    try:
        os.makedirs(args.output, exist_ok=True)
        testf = os.path.join(args.output, '.write_test')
        open(testf, 'w').close()
        os.unlink(testf)
    except Exception as e:
        print(json.dumps({'ok': False, 'error': '输出目录不可写: %s' % e}), file=sys.stderr)
        return 1

    tid = args.task_id or time.strftime('%Y%m%d_%H%M%S') + '_%d' % os.getpid()
    st = run_task(args.source, args.output, opts, tid)
    print(json.dumps({'ok': st['status'] in ('done', 'cancelled'), 'taskId': tid,
                      'status': st['status'], 'success': st['success'],
                      'failed': st['failed'], 'skipped': st['skipped']}, ensure_ascii=False))
    return 0 if st['status'] == 'done' else 1

if __name__ == '__main__':
    sys.exit(main())
