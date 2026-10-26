#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAW 归档 —— 核心处理脚本 v1.0.20
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
APP_VER  = '1.0.20'

RAW_EXTS = {'.nef','.nrw','.cr2','.cr3','.crw','.arw','.srf','.sr2','.raf','.orf','.dng','.pef','.rw2'}
JPG_EXTS = {'.jpg','.jpeg'}
VID_EXTS = {'.mp4','.mov','.mts','.m2ts','.avi','.mkv','.3gp','.mpg','.mpeg','.wmv','.flv','.m4v','.ts','.mod','.mxf'}
ALL_EXTS = RAW_EXTS | JPG_EXTS | VID_EXTS

DATE_DIR_RE   = re.compile(r'^\d{8}$')
SKIP_DIRS     = {'@eaDir', APP_DIR, '_inbox', '_exports', '_trash', '_restored',
                 'Thumbs.db', '.DS_Store', 'lost+found'}
# 飞牛外接存储挂载在 /vol00（如 /vol00/MassStorageClass、/vol00/USB_DISK），
# 必须算作可移动介质；DSM / 通用 Linux 的路径一并保留。
REMOVABLE_PFX = ('/vol00', '/volumeUSB', '/mnt/usb', '/media/', '/run/media/', '/Volumes/', '/mediausb')

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

def _ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def log_msg(st, msg):
    st.setdefault('logs', []).append({'t': _ts(), 'msg': msg})
    if len(st['logs']) > 2000:
        st['logs'] = st['logs'][-1500:]
    print('[%s] %s' % (_ts(), msg), flush=True)

def log_file(st, level, src, dest=None, msg=None):
    """逐文件日志：同时写入 state.logs（供 UI）与 stdout（进 <输出目录>/log/ 的日志文件）。

    level='OK' 时 dest 为目标相对路径（记 src -> dst 映射）；
    其余（FAIL/SKIP）用 msg 记原因。
    """
    ts = _ts()
    entry = {'t': ts, 'status': level.lower(), 'src': src}
    if level == 'OK' and dest is not None:
        entry['dst'] = dest
        line = '%s | %-4s | %s -> %s' % (ts, level, src, dest)
    else:
        entry['msg'] = msg or ''
        line = '%s | %-4s | %s | %s' % (ts, level, src, msg or '')
    st.setdefault('logs', []).append(entry)
    if len(st['logs']) > 2000:
        st['logs'] = st['logs'][-1500:]
    print(line, flush=True)

# ---- 源类型判定 ----

def is_removable(path):
    if not path:
        return False
    if sys.platform == 'win32':
        # Windows：用 GetDriveTypeW 判断盘符类型，DRIVE_REMOVABLE(2) = U 盘/读卡器/移动硬盘
        try:
            import ctypes
            drive = os.path.splitdrive(os.path.abspath(path))[0]
            if not drive:
                drive = os.path.abspath(path)[:1]
            t = ctypes.windll.kernel32.GetDriveTypeW(drive + '\\')
            return t == 2
        except Exception:
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

_ET_DATE_TAGS = ['-CreateDate', '-DateTimeOriginal', '-MediaCreateDate',
                 '-TrackCreateDate', '-FileModifyDate']
_ET_DATE_KEYS = ('ExifIFD:CreateDate', 'ExifIFD:DateTimeOriginal',
                 'QuickTime:CreateDate', 'QuickTime:MediaCreateDate', 'System:FileModifyDate')


def _et_batch_info(paths, want_make=False, chunk=100):
    """一次 exiftool 调用解析一批文件 → ({abs_path: {'dt','tag','make'}}, ok)。

    单个 test.exe 进程 vs 每个文件一个 perl 进程：1000 个视频从 ~60s 降到 ~1s。
    ok=False 表示 exiftool 不可用或调用失败，调用方应回落到逐文件 resolve_date。
    """
    info, ok = {}, False
    binp = _exiftool_bin()
    if not binp or not paths:
        return info, False
    tags = list(_ET_DATE_TAGS) + (['-Make'] if want_make else [])
    for i in range(0, len(paths), chunk):
        part = [str(p) for p in paths[i:i + chunk]]
        try:
            cmd = _et_run_prefix(binp) + ['-j', '-G1', '-n', '-m'] + tags + part
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if r.returncode != 0 or not r.stdout.strip():
                continue
            ok = True
            for o in json.loads(r.stdout):
                fp = o.get('SourceFile')
                if not fp:
                    continue
                dt = tag = None
                for k in _ET_DATE_KEYS:
                    v = o.get(k)
                    if v:
                        d = _parse_dt(v)
                        if d:
                            dt, tag = d, k.split(':')[0].lower()
                            break
                mk = None
                if want_make:
                    mk = _norm_make(o.get('IFD0:Make') or o.get('ExifIFD:Make')
                                    or o.get('Make') or '')
                info[os.path.abspath(fp)] = {'dt': dt, 'tag': tag, 'make': mk}
        except Exception:
            continue
    return info, ok


def resolve_dates(paths):
    """批量解析拍摄时间 → {path: (datetime|None, tag)}。

    视频：一次 exiftool 批量调用（每 100 个一批）；批量拿不到就按「视频用文件时间兜底」处理。
    图片：逐文件走 exifread / Pillow（纯 Python，单张几毫秒），只有它们都读不到才回落 exiftool。
    """
    res = {}
    vids = [p for p in paths if os.path.splitext(p)[1].lower() in VID_EXTS]
    info, ok = _et_batch_info(vids) if vids else ({}, False)
    for p in vids:
        it = info.get(os.path.abspath(p))
        if it and it.get('dt'):
            res[p] = (it['dt'], it['tag'])
    for p in paths:
        if p in res:
            continue
        if os.path.splitext(p)[1].lower() in VID_EXTS:
            if ok:
                # 批量已经代表过 exiftool 的结论，不必再单文件重跑
                try:
                    res[p] = (datetime.fromtimestamp(os.path.getmtime(p)), 'file_mtime')
                except Exception:
                    res[p] = (None, 'unknown')
            else:
                try:
                    res[p] = resolve_date(p)
                except Exception:
                    res[p] = (None, 'unknown')
        else:
            try:
                res[p] = resolve_date(p)
            except Exception:
                res[p] = (None, 'unknown')
    return res


def resolve_makes(paths):
    """批量识别品牌 → {path: brand|None}（「按品牌分层」用）。"""
    res = {}
    info, _ok = _et_batch_info(paths, want_make=True)
    for p in paths:
        it = info.get(os.path.abspath(p))
        mk = it.get('make') if it else None
        res[p] = mk or _get_make(p)
    return res


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

def clean_target(rel_src, dt, opts, output):
    """本文件「若无重名」应落到的路径。判重与冲突消解都以它为基准。"""
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
    return os.path.join(output, folder, new_name)


def build_target(rel_src, dt, opts, reserved, output):
    """返回 (dst, month_dst)。dst 在真冲突（同名不同内容）时才追加 _1/_2。

    「已归档」不应走到这里的后缀分支——判重由 judge_file 先做，判为 dup 的直接跳过。
    """
    ext = os.path.splitext(rel_src)[1].lower()
    new_name = os.path.basename(clean_target(rel_src, dt, opts, output))
    dst = clean_target(rel_src, dt, opts, output)

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

def do_preview(source, opts, limit=500, output=None):
    """扫描源并给出「差异视图」：新增 / 已归档 / 待校验 / 冲突 / 无日期。

    ⚠️ limit 只限制**返回给界面展示的样本条数**，绝不限制统计：total/counts/dup 一律按
    全部文件算（v1.0.19 之前 limit 会把统计一起截断，导致 500 个以上显示成 500）。
    预览不读源文件内容（避免插卡预览读几百 MB）——需要内容复核的记为 dup_unverified，
    由执行阶段逐个复核。output 缺省时退化为旧行为（按源目录推算目标名，仅供展示）。
    """
    source = os.path.abspath(source)
    out = os.path.abspath(output) if output else source
    items = list(scan_images(source, opts))
    dates = resolve_dates(items)
    maker_cache = {}
    if opts.get('brand_folder') and items:
        makes = resolve_makes(items)
        maker_cache = {os.path.relpath(p, source): makes.get(p) for p in items}
        opts['_maker_cache'] = maker_cache

    rows = []
    by_type, bad_count, conflicts = defaultdict(int), 0, 0
    counts = {'new': 0, 'dup': 0, 'dup_unverified': 0, 'missing': 0,
              'conflict': 0, 'nodate': 0}
    dup_keys, dup_bytes, sample_dups = [], 0, []
    last_archived = ''
    reserved = set()
    total_size, total_count = 0, 0
    conn = ensure_ledger(out)
    try:
        for fp in items:
            try:
                sz = os.path.getsize(fp)
                mt = int(os.path.getmtime(fp))
            except Exception:
                continue
            total_size += sz
            total_count += 1
            ext = os.path.splitext(fp)[1].lower()
            by_type[ext] += 1
            rel = os.path.relpath(fp, source)
            dt, tag = dates.get(fp) or (None, 'unknown')
            if tag in ('file_mtime', 'unknown'):
                bad_count += 1

            clean_dst = clean_target(rel, dt, opts, out)
            if ext in (RAW_EXTS | JPG_EXTS) and tag == 'unknown':
                verdict, ev = 'nodate', {}
            else:
                verdict, ev = judge_file(conn, fp, rel, sz, mt, clean_dst, out, opts, verify=False)
            counts[verdict] = counts.get(verdict, 0) + 1
            if verdict in ('dup', 'dup_unverified', 'missing'):
                dup_keys.append('%s|%d' % (rel, sz))
                if verdict != 'missing':
                    dup_bytes += sz
                if ev.get('archived_at') and ev['archived_at'] > last_archived:
                    last_archived = ev['archived_at']
                if len(sample_dups) < 100:
                    sample_dups.append({'src': rel, 'size': sz,
                                        'prev_dst': ev.get('prev_dst'),
                                        'archived_at': ev.get('archived_at'),
                                        'task': ev.get('task'), 'level': ev.get('level'),
                                        'verdict': verdict})
            if verdict == 'conflict':
                conflicts += 1

            if limit and len(rows) >= limit:
                continue          # 样本够了，但统计照算
            dst, _md = build_target(rel, dt, opts, reserved, out)
            rows.append({'src': rel, 'size': sz,
                         'date': dt.strftime('%Y-%m-%d') if dt else None,
                         'date_from': tag,
                         'dst_rel': os.path.relpath(dst, out) if dst else None,
                         'bad': tag in ('file_mtime', 'unknown'),
                         'verdict': verdict,
                         'skip': (ext in (RAW_EXTS | JPG_EXTS) and tag == 'unknown')})
        vk = volume_key(source)
        vol = volume_seen(conn, vk)
    finally:
        conn.close()

    all_dates = sorted({d.strftime('%Y-%m-%d') for (d, _t) in dates.values() if d})
    guard = make_guard(source, out, opts, dup_keys) if dup_keys else ''
    return {'source': source, 'output': out, 'removable': is_removable(source),
            'total': total_count, 'size': total_size, 'by_type': dict(by_type),
            'date_range': [all_dates[0], all_dates[-1]] if all_dates else [None, None],
            'bad_count': bad_count, 'conflicts': conflicts,
            'counts': counts,
            'dup': {'count': counts['dup'] + counts['dup_unverified'],
                    'verified': counts['dup'], 'unverified': counts['dup_unverified'],
                    'missing': counts['missing'], 'bytes': dup_bytes,
                    'last_at': last_archived, 'sample': sample_dups},
            'volume': vol, 'dup_guard': guard,
            'raw_skip_hint': counts['nodate'],
            'removable_note': 'move 模式归档成功后将清空源设备' if is_removable(source) else '',
            'exiftool': et_available(),
            'sample_shown': len(rows),
            'sample_limited': bool(limit and total_count > len(rows)),
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

# ======================== 重复归档防护（Dup Guard） ========================
#
# 问题：SD/TF/U 盘上的照片删不掉（或忘删），下次插卡再归档 → 同一批照片被再处理一遍，
#       输出目录里长出 _1/_2/_3 副本。原实现只在「当前任务」内按 (rel,size) 去重，
#       跨天/跨任务毫无记忆，且 build_target 把「已归档」和「真重名」一视同仁地追加后缀。
#
# 「处理过」的定义（三级证据，成本递增，命中即停）：
#   L1 元数据：basename+size+mtime 命中台账，且台账记录的 dst 文件仍在 → 零读盘
#   L2 内容：  同名同 size 的台账记录 → 与归档文件比对内容（默认头尾各 256KB）
#   L3 现场：  当前选项算出的目标路径已存在 → 比对内容（台账为空/丢失时的兜底）
#
# 口径（2026-10 需求确认）：
#   · 默认跳过已归档；要重处理必须显式 force（GUI 需先预览拿 dupGuard，CLI 需 --dup-policy force）
#   · 跨「输出目录」不算重复 —— 归档到另一个目录视为新文件
#   · 内容复核默认 sampled（头尾各 256KB），可选 full（全文件哈希，强迫症模式）
#   · 宁可重复，不可丢失：判不准一律按新文件处理

LEDGER_DB  = 'ledger.sqlite3'
HASH_CHUNK = 256 * 1024
GUARD_TTL  = 30 * 60
HASH_MODES = ('sampled', 'full')

_LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS archived (
  uid         INTEGER PRIMARY KEY AUTOINCREMENT,
  k1          TEXT,
  name        TEXT NOT NULL,
  size        INTEGER NOT NULL,
  mtime       INTEGER,
  shot_date   TEXT,
  dst_rel     TEXT,
  output      TEXT,
  task_id     TEXT,
  brand       INTEGER DEFAULT 0,
  archived_at TEXT,
  state       TEXT DEFAULT 'ok'
);
CREATE INDEX IF NOT EXISTS ix_arch_k1   ON archived(k1);
CREATE INDEX IF NOT EXISTS ix_arch_name ON archived(name, size, output);
CREATE TABLE IF NOT EXISTS meta (
  k           TEXT PRIMARY KEY,
  v           TEXT
);
CREATE TABLE IF NOT EXISTS volumes (
  volkey      TEXT PRIMARY KEY,
  last_task   TEXT,
  last_at     TEXT,
  last_count  INTEGER,
  last_output TEXT
);
"""


def ledger_path():
    return os.path.join(state_root(), LEDGER_DB)


def ledger_conn():
    import sqlite3
    p = ledger_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    c = sqlite3.connect(p, timeout=10.0)
    c.row_factory = sqlite3.Row
    try:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA busy_timeout=5000')
        c.executescript(_LEDGER_SCHEMA)
    except Exception:
        pass
    return c


def _k1(name, size, mtime):
    """L1 键：文件名 + 大小 + mtime。三者同时一致 = 同一份源文件（无需读盘）。"""
    return hashlib.sha1(('%s|%d|%d' % (name, int(size), int(mtime or 0))).encode('utf-8')).hexdigest()


def fp_content(path, mode='sampled'):
    """内容指纹。sampled = size + 头 256KB + 尾 256KB；full = 全文件。"""
    size = os.path.getsize(path)
    h = hashlib.sha1(str(size).encode('ascii'))
    with open(path, 'rb') as f:
        if mode == 'full':
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        else:
            h.update(f.read(HASH_CHUNK))
            if size > HASH_CHUNK * 2:
                f.seek(-HASH_CHUNK, os.SEEK_END)
                h.update(f.read(HASH_CHUNK))
    return h.hexdigest()


def compare_content(a, b, mode='sampled'):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        return fp_content(a, mode) == fp_content(b, mode)
    except Exception:
        return False


def ledger_record(conn, name, size, mtime, dst_rel, output, task_id,
                  shot_date=None, brand=0):
    conn.execute(
        'INSERT INTO archived (k1,name,size,mtime,shot_date,dst_rel,output,task_id,'
        "brand,archived_at,state) VALUES (?,?,?,?,?,?,?,?,?,?,'ok')",
        (_k1(name, size, mtime), name, int(size), int(mtime or 0), shot_date,
         dst_rel, os.path.abspath(output), task_id, int(brand),
         datetime.now().strftime('%Y-%m-%d %H:%M:%S')))


def ledger_invalidate(conn, output, dst_rels):
    """回滚/删除后让台账记录失效，避免下次误判「已归档」而跳过。"""
    n = 0
    for rel in dst_rels or []:
        try:
            cur = conn.execute(
                "UPDATE archived SET state='rolled_back' WHERE output=? AND dst_rel=? AND state='ok'",
                (os.path.abspath(output), rel))
            n += cur.rowcount or 0
        except Exception:
            pass
    return n


def rebuild_from_reports(conn, output):
    """从 <output>/log/_report_*.json 回填台账（升级后首次运行 / 台账丢失时）。

    报告里有 src/size/dst/date/task_id，但没有源 mtime，故 k1 留空：
    这类记录靠「同名同 size + 与归档文件比内容」命中，命中后自愈写入 k1。
    """
    out = os.path.abspath(output)
    d = log_dir(out)
    if not os.path.isdir(d):
        return 0
    n = 0
    for fn in sorted(os.listdir(d)):
        if not (fn.startswith('_report_') and fn.endswith('.json')):
            continue
        try:
            rep = json.loads(Path(d, fn).read_text(encoding='utf-8'))
        except Exception:
            continue
        for it in rep.get('items') or []:
            src, dst, sz = it.get('src'), it.get('dst'), it.get('size')
            if not src or not dst or sz is None:
                continue
            name = os.path.basename(src)
            try:
                dup = conn.execute(
                    'SELECT 1 FROM archived WHERE name=? AND size=? AND dst_rel=? AND output=? LIMIT 1',
                    (name, int(sz), dst, out)).fetchone()
            except Exception:
                continue
            if dup:
                continue
            fin = (rep.get('finished_at') or '').replace('T', ' ')[:19]
            conn.execute(
                'INSERT INTO archived (k1,name,size,mtime,shot_date,dst_rel,output,task_id,'
                "brand,archived_at,state) VALUES (NULL,?,?,NULL,?,?,?,?,0,?,'ok')",
                (name, int(sz), it.get('date'), dst, out, rep.get('task_id'), fin))
            n += 1
    return n


def ensure_ledger(output=None):
    """取台账连接；某个输出目录还没有任何记录时，先用它的历史报告回填（每个目录只尝试一次）。

    回填标记记在 meta 表，避免每次预览都去扫一遍 log/ 下的历史报告。
    """
    conn = ledger_conn()
    if not output:
        return conn
    out = os.path.abspath(output)
    key = 'backfill:' + out
    try:
        n_out = conn.execute('SELECT COUNT(*) FROM archived WHERE output=?', (out,)).fetchone()[0]
        done = conn.execute('SELECT 1 FROM meta WHERE k=?', (key,)).fetchone() is not None
    except Exception:
        return conn
    if n_out == 0 and not done:
        try:
            rebuild_from_reports(conn, out)
            conn.execute('INSERT OR REPLACE INTO meta (k,v) VALUES (?,?)', (key, str(int(now()))))
            conn.commit()
        except Exception:
            pass
    return conn


def judge_file(conn, path, rel, size, mtime, clean_dst, output, opts, verify=True):
    """判定一个源文件的归属。

    verify=False（预览）：不读盘做内容比对，同 size 的目标只报 dup_unverified，数字可能略保守；
    verify=True（执行）：同 size 一律做内容复核，判不准按「新文件」处理（宁可重复不可丢失）。
    返回 (verdict, evidence)；verdict ∈ new / dup / dup_unverified / missing / conflict / nodate
    """
    out = os.path.abspath(output)
    name = os.path.basename(rel)
    mode = opts.get('dup_hash') if opts.get('dup_hash') in HASH_MODES else 'sampled'

    # ---- L1：元数据命中（零读盘）----
    try:
        r = conn.execute(
            "SELECT dst_rel,task_id,archived_at FROM archived "
            "WHERE k1=? AND output=? AND state='ok' ORDER BY archived_at DESC LIMIT 1",
            (_k1(name, size, mtime), out)).fetchone()
    except Exception:
        r = None
    if r and r['dst_rel']:
        ev = {'level': 'l1', 'prev_dst': r['dst_rel'], 'task': r['task_id'],
              'archived_at': r['archived_at']}
        if os.path.exists(os.path.join(out, r['dst_rel'])):
            return 'dup', ev
        return 'missing', ev

    # ---- L2：同名同 size 的历史记录 → 与归档文件比内容 ----
    try:
        rows = conn.execute(
            "SELECT dst_rel,task_id,archived_at FROM archived "
            "WHERE name=? AND size=? AND output=? AND state='ok' "
            "ORDER BY archived_at DESC LIMIT 5",
            (name, int(size), out)).fetchall()
    except Exception:
        rows = []
    for r in rows:
        if not r['dst_rel']:
            continue
        prev = os.path.join(out, r['dst_rel'])
        if not os.path.exists(prev):
            continue
        ev = {'level': 'l2', 'prev_dst': r['dst_rel'], 'task': r['task_id'],
              'archived_at': r['archived_at']}
        if not verify:
            return 'dup_unverified', ev
        if compare_content(path, prev, mode):
            # 自愈：补上 k1，下次回到零读盘的 L1
            try:
                conn.execute(
                    "UPDATE archived SET k1=?, mtime=? WHERE output=? AND dst_rel=? AND state='ok'",
                    (_k1(name, size, mtime), int(mtime or 0), out, r['dst_rel']))
                conn.commit()
            except Exception:
                pass
            return 'dup', ev

    # ---- L3：目标现场（台账缺失/丢失时的兜底）----
    if clean_dst and os.path.exists(clean_dst):
        try:
            same_size = os.path.getsize(clean_dst) == int(size)
        except OSError:
            same_size = False
        ev = {'level': 'l3', 'prev_dst': os.path.relpath(clean_dst, out)}
        if not same_size:
            return 'conflict', ev
        if not verify:
            return 'dup_unverified', ev
        if compare_content(path, clean_dst, mode):
            return 'dup', ev
        return 'conflict', ev

    return 'new', {}


def volume_key(path):
    """介质指纹（只用于「这张卡上次处理过」的提示，不参与判定）。"""
    try:
        if sys.platform == 'win32':
            import ctypes
            drive = os.path.splitdrive(os.path.abspath(path))[0] + '\\'
            serial = ctypes.c_ulong(0)
            ctypes.windll.kernel32.GetVolumeInformationW(
                drive, None, 0, ctypes.byref(serial), None, None, None, 0)
            return 'win-%08x' % serial.value
        if sys.platform == 'darwin':
            return 'mac-%d' % os.stat(path).st_dev
        p = os.path.realpath(os.path.abspath(path))
        mp, fst = p, ''
        with open('/proc/mounts', encoding='utf-8', errors='ignore') as f:
            best = None
            for ln in f:
                parts = ln.split()
                if len(parts) >= 3 and (p == parts[1] or p.startswith(parts[1].rstrip('/') + '/')):
                    if best is None or len(parts[1]) > len(best[1]):
                        best = parts
            if best:
                mp, fst = best[1], best[2]
        st = os.statvfs(path)
        total = st.f_blocks * (st.f_frsize or st.f_bsize or 1)
        return hashlib.sha1(('%s|%s|%d' % (mp, fst, total)).encode('utf-8')).hexdigest()[:16]
    except Exception:
        return ''


def volume_seen(conn, vk):
    if not vk:
        return {'seen_before': False}
    try:
        r = conn.execute('SELECT * FROM volumes WHERE volkey=?', (vk,)).fetchone()
    except Exception:
        r = None
    if not r:
        return {'seen_before': False}
    return {'seen_before': True, 'last_at': r['last_at'],
            'last_count': r['last_count'], 'last_output': r['last_output'],
            'last_task': r['last_task']}


def volume_touch(conn, vk, task_id, count, output):
    if not vk:
        return
    try:
        conn.execute('INSERT OR REPLACE INTO volumes (volkey,last_task,last_at,last_count,last_output) '
                     'VALUES (?,?,?,?,?)',
                     (vk, task_id, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                      int(count), os.path.abspath(output)))
        conn.commit()
    except Exception:
        pass


# ---- 确认门（预览签发 → 执行校验）----

def _secret():
    p = os.path.join(state_root(), 'secret')
    try:
        if os.path.exists(p):
            s = open(p, encoding='utf-8').read().strip()
            if s:
                return s
    except Exception:
        pass
    s = hashlib.sha1(os.urandom(32)).hexdigest()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(s)
        os.chmod(p, 0o600)
    except Exception:
        pass
    return s


def opts_sig(opts):
    keys = ('brand_folder', 'handle_jpg', 'handle_video', 'month_dir',
            'staging', 'mode', 'dup_hash')
    return hashlib.sha1(json.dumps({k: opts.get(k) for k in keys},
                                   sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]


def make_guard(source, output, opts, dup_keys):
    """预览签发确认凭据：绑定 源/输出/选项/重复文件集合，30 分钟有效。"""
    raw = '%s|%s|%s|%s|%s' % (_secret(), os.path.abspath(source), os.path.abspath(output),
                              opts_sig(opts), ','.join(sorted(dup_keys)))
    g = hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]
    rec = {'source': os.path.abspath(source), 'output': os.path.abspath(output),
           'opts': opts_sig(opts), 'dup_count': len(dup_keys), 'ts': now()}
    try:
        p = os.path.join(state_root(), 'guards', g + '.json')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        atomic_write(p, rec)
    except Exception:
        pass
    return g


def check_guard(g, source, output, opts):
    if not g:
        return False, '缺少确认凭据（dupGuard）'
    p = os.path.join(state_root(), 'guards', os.path.basename(str(g)) + '.json')
    if not os.path.exists(p):
        return False, '确认凭据不存在或已失效，请重新预览后再确认'
    try:
        rec = json.loads(open(p, encoding='utf-8').read())
    except Exception:
        return False, '确认凭据损坏，请重新预览'
    if now() - float(rec.get('ts') or 0) > GUARD_TTL:
        return False, '确认凭据已过期（30 分钟），请重新预览'
    if rec.get('source') != os.path.abspath(source) or rec.get('output') != os.path.abspath(output):
        return False, '确认凭据与本次源/输出目录不匹配，请重新预览'
    if rec.get('opts') != opts_sig(opts):
        return False, '确认凭据与本次选项不匹配（品牌分层/暂存/模式等已改动），请重新预览'
    return True, ''


def ledger_stats(output=None):
    conn = ensure_ledger(output)
    try:
        total = conn.execute("SELECT COUNT(*) FROM archived WHERE state='ok'").fetchone()[0]
        rolled = conn.execute("SELECT COUNT(*) FROM archived WHERE state='rolled_back'").fetchone()[0]
        outs = conn.execute("SELECT output, COUNT(*) c FROM archived WHERE state='ok' "
                            "GROUP BY output ORDER BY c DESC LIMIT 20").fetchall()
        last = conn.execute("SELECT MAX(archived_at) FROM archived").fetchone()[0]
    finally:
        conn.close()
    return {'ok': True, 'db': ledger_path(), 'total': total, 'rolled_back': rolled,
            'outputs': [{'output': r['output'], 'count': r['c']} for r in outs],
            'last_archived_at': last}


def ledger_prune(output=None, days=180):
    """清理 N 天前的记录（默认 180 天）。只删元数据，不动归档文件。"""
    cutoff = datetime.fromtimestamp(now() - days * 86400).strftime('%Y-%m-%d %H:%M:%S')
    conn = ensure_ledger(output)
    try:
        cur = conn.execute('DELETE FROM archived WHERE archived_at < ? AND archived_at != ""', (cutoff,))
        n = cur.rowcount or 0
        conn.commit()
    finally:
        conn.close()
    return {'ok': True, 'deleted': n, 'cutoff': cutoff}


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
    # 台账联动：这批归档文件已移走，必须让它失效，否则下次插卡会被误判「已归档」而跳过
    try:
        conn = ensure_ledger(output)
        n_inv = ledger_invalidate(conn, output, [it.get('dst') for it in st.get('done', []) if it.get('dst')])
        conn.commit()
        conn.close()
    except Exception:
        n_inv = 0
    return {'ok': True, 'restored': n, 'to': moved, 'ledger_invalidated': n_inv}

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
        st['skipped_dup'] = 0
        st['skipped_nodate'] = 0
        st['failed'] = 0
        items = list(scan_images(src, opts))
        st['total'] = len(items)
        save()
        log_msg(st, '待处理 %d 个文件' % len(items))

        # 批量读取拍摄日期：视频走一次 exiftool（每 100 个一批），图片逐文件（exifread 很快）
        log_msg(st, '正在读取拍摄日期（%d 个文件，视频批量解析）...' % len(items))
        dates = resolve_dates(items)
        maker_cache = {}
        if opts.get('brand_folder'):
            log_msg(st, '正在识别品牌（仅本次）...')
            makes = resolve_makes(items)
            maker_cache = {os.path.relpath(p, src): makes.get(p) for p in items}
        opts['_maker_cache'] = maker_cache

        mode_dup = opts.get('dup_policy') or 'skip'
        hash_mode = opts.get('dup_hash') if opts.get('dup_hash') in HASH_MODES else 'sampled'
        opts['dup_hash'] = hash_mode
        st['dup_policy'] = mode_dup
        st['dup_hash'] = hash_mode
        conn = ensure_ledger(output)
        log_msg(st, '重复检测: %s（默认跳过已归档）｜内容复核: %s%s'
                % ('强制重新处理' if mode_dup == 'force' else '跳过已归档',
                   '全文件哈希' if hash_mode == 'full' else '头尾各 256KB',
                   '｜⚠ 本次会为已归档文件生成 _1/_2 副本' if mode_dup == 'force' else ''))
        save()
        try:
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
                    mt = int(os.path.getmtime(fp))
                except Exception:
                    sz, mt = 0, 0
                key = (rel, sz)
                if key in done_key:
                    st['skipped'] += 1
                    continue
                dt, tag = dates.get(fp) or (None, 'unknown')
                if dt is None:
                    st['skipped'] += 1
                    st['skipped_nodate'] += 1
                    done_key.add(key)
                    st['done'].append({'src': rel, 'size': sz, 'status': 'skip', 'reason': 'no_date'})
                    log_file(st, 'SKIP', rel, msg='无拍摄日期，跳过')
                    save()
                    continue

                clean_dst = clean_target(rel, dt, opts, output)
                if mode_dup == 'skip':
                    verdict, ev = judge_file(conn, fp, rel, sz, mt, clean_dst,
                                             output, opts, verify=True)
                    if verdict in ('dup', 'dup_unverified'):
                        st['skipped_dup'] += 1
                        st['skipped'] += 1
                        done_key.add(key)
                        st['done'].append({'src': rel, 'size': sz, 'status': 'skip',
                                           'reason': 'archived',
                                           'archived_at': ev.get('archived_at'),
                                           'prev_dst': ev.get('prev_dst')})
                        log_file(st, 'SKIP', rel,
                                 msg='已归档过（%s｜依据 %s）%s'
                                     % ((ev.get('archived_at') or '—')[:16],
                                        ev.get('level') or '?',
                                        ('，原文件：' + ev['prev_dst']) if ev.get('prev_dst') else ''))
                        save()
                        continue
                    if verdict == 'missing':
                        log_msg(st, '记录在案但归档文件已不在原位，重新归档: %s' % rel)

                dst, mdst = build_target(rel, dt, opts, reserved, output)
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    # 归档统一用 copy2（先落盘成功再谈清源）。move 模式的“删除源文件”交给
                    # 归档完成后的 do_cleanup 统一处理，避免 shutil.move（copy+unlink 耦合）
                    # 在源不可删（如外接存储只读、或应用用户对源目录无删除权限）时抛异常，
                    # 导致“文件已复制到目标、日志却记全部失败”。
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
                    log_file(st, 'OK', rel, dest=ent['dst'])
                    try:
                        ledger_record(conn, os.path.basename(rel), sz, mt,
                                      ent['dst'], output, task_id,
                                      shot_date=ent['date'],
                                      brand=1 if opts.get('brand_folder') else 0)
                        if idx % 50 == 0:
                            conn.commit()
                    except Exception as le:
                        log_msg(st, '[台账] 写入失败（不影响归档）: %s' % le)
                except Exception as e:
                    st['failed'] += 1
                    log_file(st, 'FAIL', rel, msg=str(e))
                save()
        finally:
            try:
                conn.commit()
            except Exception:
                pass
            try:
                volume_touch(conn, volume_key(source), task_id,
                             st.get('success', 0), output)
            except Exception:
                pass
            conn.close()

        if mode == 'move' and st['to_delete']:
            # move 模式：归档成功后清空源目录（外接卡或本地目录都处理）。
            # 清源失败不影响归档结果——文件已安全落盘，只是源文件保留（权限不足时会在此告警）。
            log_msg(st, '[清源] 归档完成，开始清空源目录上对应文件 ...')
            r = do_cleanup(output, task_id)
            if r.get('ok'):
                msg = '[清源] 已删除 %d 个文件' % r['deleted']
                if r['kept']:
                    msg += '，%d 个因大小校验未过而保留' % len(r['kept'])
                log_msg(st, msg)
                if r['fail']:
                    log_msg(st, '[清源] 以下 %d 个删除失败（源文件保留，归档已成功）: %s'
                            % (len(r['fail']), '; '.join(r['fail'][:5])))
                    detail = ' '.join(r['fail'])
                    if any(k in detail for k in ('Permission denied', 'Read-only', 'EACCES', 'EROFS')):
                        log_msg(st, '[清源] 原因：源目录对当前应用用户不可写（外接存储常以只读权限挂载）；'
                                    '请手动删除源文件，或改用「复制」模式。归档结果不受影响，无需重新归档。')
                    else:
                        log_msg(st, '[清源] 请检查源目录写权限，或手动删除源文件；归档结果不受影响。')
            else:
                log_msg(st, '[清源] 跳过（文件已安全归档）: %s，后续可用 --cleanup 补清' % r.get('error'))

        if st['status'] != 'cancelled':
            st['status'] = 'done'
        st['finished_at'] = now()
        fin = datetime.fromtimestamp(st['finished_at']).strftime('%Y-%m-%d %H:%M:%S')
        log_msg(st, '完成: 成功 %d / 跳过 %d（已归档 %d、无日期 %d）/ 失败 %d，完成时间 %s'
                % (st['success'], st['skipped'], st.get('skipped_dup', 0),
                   st.get('skipped_nodate', 0), st['failed'], fin))
        save()
        write_report(output, task_id, st)
    except Exception as e:
        st['status'] = 'error'
        st['error'] = str(e)
        log_msg(st, '异常: %s' % e)
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
        'dup_policy': st.get('dup_policy', 'skip'), 'dup_hash': st.get('dup_hash', 'sampled'),
        'total': st['total'], 'success': st['success'],
        'failed': st['failed'], 'skipped': st['skipped'],
        'skipped_dup': st.get('skipped_dup', 0),
        'skipped_nodate': st.get('skipped_nodate', 0),
        'items': [d for d in st.get('done', []) if d.get('status') == 'ok'],
        'skipped_items': [d for d in st.get('done', []) if d.get('status') == 'skip'],
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
    # —— 重复归档防护 ——
    ap.add_argument('--dup-policy', choices=['skip', 'force'], default='skip',
                    help='skip=跳过已归档（默认）, force=重新处理已归档（会生成 _1/_2 副本）')
    ap.add_argument('--dup-guard', default=None,
                    help='预览签发的确认凭据（GUI/API 传 force 时必填）')
    ap.add_argument('--require-guard', action='store_true',
                    help='强制校验 --dup-guard（服务端调用时使用）')
    ap.add_argument('--dup-hash', choices=list(HASH_MODES), default='sampled',
                    help='内容复核强度: sampled=头尾各 256KB（默认）, full=全文件哈希')
    ap.add_argument('--rebuild-ledger', metavar='DIR', default=None,
                    help='从 <DIR>/log/_report_*.json 回填台账后退出')
    ap.add_argument('--ledger-stats', action='store_true', help='打印台账统计后退出')
    ap.add_argument('--ledger-prune', type=int, metavar='DAYS', default=None,
                    help='清理 N 天前的台账记录后退出')
    args = ap.parse_args()

    opts = {'brand_folder': args.brand_folder, 'handle_jpg': args.handle_jpg,
            'handle_video': args.handle_video, 'month_dir': args.month_dir,
            'staging': args.staging, 'mode': args.mode,
            'dup_policy': args.dup_policy, 'dup_hash': args.dup_hash,
            'dup_guard': args.dup_guard}

    if args.doctor:
        print(json.dumps({'app': APP_NAME, 'version': APP_VER,
                          'python': sys.version.split()[0],
                          'exifread': bool(exifread), 'pillow': bool(Image),
                          'exiftool': _exiftool_bin() or None,
                          'ledger': ledger_path(),
                          'perl': os.path.exists('/usr/bin/perl')}, ensure_ascii=False))
        return 0
    if args.ledger_stats:
        print(json.dumps(ledger_stats(args.output), ensure_ascii=False))
        return 0
    if args.ledger_prune:
        print(json.dumps(ledger_prune(args.output, args.ledger_prune), ensure_ascii=False))
        return 0
    if args.rebuild_ledger:
        conn = ledger_conn()
        try:
            n = rebuild_from_reports(conn, args.rebuild_ledger)
            conn.commit()
        finally:
            conn.close()
        print(json.dumps({'ok': True, 'added': n, 'from': args.rebuild_ledger,
                          'db': ledger_path()}, ensure_ascii=False))
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
        print(json.dumps(do_preview(args.source, opts, output=args.output), ensure_ascii=False))
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

    # 确认门：force 需显式凭据（服务端调用方要求 --require-guard）
    if args.dup_policy == 'force' and args.require_guard:
        okg, errg = check_guard(args.dup_guard, args.source, args.output, opts)
        if not okg:
            print(json.dumps({'ok': False, 'code': 'need_confirm', 'error': errg},
                             ensure_ascii=False), file=sys.stderr)
            return 2

    st = run_task(args.source, args.output, opts, tid)
    print(json.dumps({'ok': st['status'] in ('done', 'cancelled'), 'taskId': tid,
                      'status': st['status'], 'success': st['success'],
                      'failed': st['failed'], 'skipped': st['skipped'],
                      'skipped_dup': st.get('skipped_dup', 0),
                      'skipped_nodate': st.get('skipped_nodate', 0)},
                     ensure_ascii=False))
    return 0 if st['status'] == 'done' else 1

if __name__ == '__main__':
    sys.exit(main())
