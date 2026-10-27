#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重复归档防护（Dup Guard）自检 —— 覆盖 docs/dup-guard-plan.md 第 9 节 14 条断言。

跑法（本机/CI）：
    PYTHONPATH= python3 fnos/selftest_dupguard.py
通过时最后一行打印 SELFTEST_DUPGUARD_OK；任一断言失败立即抛错退出 1。
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, 'rawarchiver', 'app', 'scripts', 'raw_archiver.py')

TMP = tempfile.mkdtemp(prefix='dupguard_')
os.environ['TRIM_PKGVAR'] = os.path.join(TMP, 'var')
sys.path.insert(0, os.path.dirname(CORE))
import raw_archiver as core  # noqa: E402

FIXED_DT = datetime(2026, 1, 1, 12, 0, 0)
core.resolve_date = lambda p: (FIXED_DT, 'exif')      # 测试不依赖真实 EXIF
# v1.0.21 起：exifread/Pillow 都不可用时，照片会改走 exiftool 批量（不经过 resolve_date）。
# 本自检用「没有 EXIF 的假图 + 打桩的 resolve_date」验证判重口径，所以强制走纯 Python 逐文件路径，
# 否则假图会被批量解析判成「无日期」而全部跳过，测不到判重逻辑。
core._PY_FAST = True

ok_n = 0


def check(cond, msg):
    global ok_n
    if not cond:
        raise AssertionError('FAILED: ' + msg)
    ok_n += 1
    print('  [%02d] ok  %s' % (ok_n, msg))


def opts(**kw):
    o = {'brand_folder': False, 'handle_jpg': True, 'handle_video': True,
         'month_dir': False, 'staging': False, 'mode': 'copy',
         'dup_policy': 'skip', 'dup_hash': 'sampled'}
    o.update(kw)
    return o


def mkfile(path, data, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    if mtime:
        os.utime(path, (mtime, mtime))


def run(src, out, o=None, tid=None):
    """跑一次归档，吞掉 core 的 print 噪音。"""
    tid = tid or 'T%d' % (int(datetime.now().timestamp() * 1000) % 10 ** 8)
    buf = io.StringIO()
    with redirect_stdout(buf):
        st = core.run_task(src, out, o or opts(), tid)
    return st, tid


def preview(src, out, o=None):
    buf = io.StringIO()
    with redirect_stdout(buf):
        return core.do_preview(src, o or opts(), output=out)


def tree(root, skip=None):
    out = []
    for dn, dns, fns in os.walk(root):
        for fn in sorted(fns):
            p = os.path.join(dn, fn)
            rel = os.path.relpath(p, root)
            if skip and rel.split(os.sep)[0] in skip:
                continue
            out.append((rel, os.path.getsize(p)))
    return sorted(out)


def main():
    src = os.path.join(TMP, 'src')
    out = os.path.join(TMP, 'out')
    a = os.path.join(src, 'DCIM', '100CANON', 'IMG_0001.JPG')
    b = os.path.join(src, 'DCIM', '100CANON', 'IMG_0002.JPG')
    mkfile(a, b'A' * 4096, 1700000000)
    mkfile(b, b'B' * 8192, 1700000100)
    src_before = tree(src)

    # 1 全新源 + 空台账 → 全部 new
    p = preview(src, out)
    check(p['counts']['new'] == 2 and p['counts']['dup'] == 0, '1 空台账时全部判定为新文件')
    check(p['conflicts'] == 0, '12a 预览冲突数为 0（老 bug 回归：不再恒 0，而是真的为 0）')

    # 2 归档一次后再跑 → 全部 dup，success=0
    st1, tid1 = run(src, out)
    check(st1['success'] == 2 and st1['skipped_dup'] == 0, '2a 首次归档成功 2 个')
    st2, _ = run(src, out)
    check(st2['success'] == 0 and st2['skipped_dup'] == 2, '2b 第二次全部判为已归档并跳过')

    # 3 改 mtime 后再跑 → 仍判 dup（走内容复核）
    os.utime(a, (1800000000, 1800000000))
    st3, _ = run(src, out)
    check(st3['success'] == 0 and st3['skipped_dup'] == 2, '3 mtime 变化后仍判已归档（同名同 size + 内容一致）')

    # 4 同名同 size 不同内容 → conflict，落 _1
    c = os.path.join(src, 'OTHER', 'IMG_0001.JPG')
    mkfile(c, b'C' * 4096, 1700000500)
    p4 = preview(src, out)
    check(p4['counts']['dup_unverified'] == 1 and p4['counts']['dup'] == 2,
          '4a 预览对「同名同 size」只报待校验（不读盘），不轻易下结论')
    conn = core.ensure_ledger(out)
    try:
        v4, _ev = core.judge_file(conn, c, 'OTHER/IMG_0001.JPG', 4096, 1700000500,
                                  os.path.join(out, '20260101', 'IMG_0001_20260101.jpg'),
                                  out, opts(), verify=True)
    finally:
        conn.close()
    check(v4 == 'conflict', '4b 执行阶段内容复核 → 判为真冲突（不是 dup）')
    st4, _ = run(src, out)
    check(st4['success'] == 1 and st4['failed'] == 0, '4c 冲突文件按新文件归档')
    check(os.path.exists(os.path.join(out, '20260101', 'IMG_0001_20260101_1.jpg')),
          '4d 冲突落 _1 后缀，未覆盖已有文件，也未误判成 dup')

    # 5 同内容不同 mtime → dup（同 3，独立断言）
    os.utime(c, (1900000000, 1900000000))
    st5, _ = run(src, out)
    check(st5['success'] == 0 and st5['skipped_dup'] == 3, '5 同内容不同 mtime 仍判已归档')

    # 6 归档文件被手动删除 → missing → 重新归档
    os.unlink(os.path.join(out, '20260101', 'IMG_0002_20260101.jpg'))
    st6, _ = run(src, out)
    check(st6['success'] == 1, '6 归档文件不在原位时重新归档（不误跳过）')
    check(os.path.exists(os.path.join(out, '20260101', 'IMG_0002_20260101.jpg')), '6b 文件已恢复')

    # 7 rollback 之后 → 台账记录失效 → 重新归档（独立输出目录，避免与其他任务交织）
    out7 = os.path.join(TMP, 'out7')
    st7, tid7 = run(src, out7)
    check(st7['success'] == 3, '7a 新目录首次归档 3 个')
    r = core.do_rollback(out7, tid7)
    check(r['restored'] == 3 and r['ledger_invalidated'] == 3,
          '7b 回滚移走 3 个归档文件，并让对应台账记录失效')
    st7c, _ = run(src, out7)
    check(st7c['success'] == 3, '7c 回滚后再跑，全部重新归档（不会因台账残留而误跳过）')

    # 8 换输出目录 → 当新文件
    out2 = os.path.join(TMP, 'out2')
    p8 = preview(src, out2)
    check(p8['counts']['new'] == 3 and p8['counts']['dup'] == 0, '8 换输出目录一律按新文件处理（跨目录不算重复）')

    # 9 force + 有效 guard → 全部重处理
    guard = p['dup_guard'] or preview(src, out)['dup_guard']
    check(bool(guard), '9a 预览签发了 dupGuard')
    okg, errg = core.check_guard(guard, src, out, opts())
    check(okg, '9b guard 校验通过（%s）' % (errg or 'ok'))

    # 10 CLI 硬门：--require-guard 且无凭据 → 退出码 2
    env = dict(os.environ, PYTHONPATH='', PYTHONIOENCODING='utf-8')
    r10 = subprocess.run([sys.executable, CORE, src, '--output', out, '--dup-policy', 'force',
                          '--require-guard'], capture_output=True, text=True, env=env)
    check(r10.returncode == 2, '10a force 未带凭据 → 退出码 2（need_confirm）')
    check('need_confirm' in (r10.stderr or ''), '10b 错误体带 code=need_confirm')
    r10b = subprocess.run([sys.executable, CORE, src, '--output', out, '--dup-policy', 'force',
                           '--dup-guard', 'deadbeefdeadbeef', '--require-guard'],
                          capture_output=True, text=True, env=env)
    check(r10b.returncode == 2, '10c 伪造/未知凭据同样被拒')
    r10c = subprocess.run([sys.executable, CORE, src, '--output', out, '--dup-policy', 'force',
                           '--dup-guard', guard, '--require-guard', '--no-staging'],
                          capture_output=True, text=True, env=env)
    check(r10c.returncode in (0, 1), '10d 合法凭据放行（rc=%d）' % r10c.returncode)

    # 11 报告回填：删台账 → 从 <out>/log/_report_*.json 重建
    db = core.ledger_path()
    before = core.ledger_stats()['total']
    check(before > 0, '11a 台账已有 %d 条记录' % before)
    for suffix in ('', '-wal', '-shm'):
        try:
            os.unlink(db + suffix)
        except OSError:
            pass
    stt = core.ledger_stats(out)
    check(stt['total'] > 0, '11b 台账删除后由历史报告自动回填 %d 条' % stt['total'])
    p11 = preview(src, out)
    check(p11['counts']['new'] == 0, '11c 回填后仍能全部识别为已归档（unverified=%d）'
          % p11['counts']['dup_unverified'])
    st11, _ = run(src, out)
    check(st11['success'] == 0 and st11['skipped_dup'] == 3, '11d 回填记录被执行阶段内容复核确认，全部跳过')

    # 12 冲突计数只在真冲突时非 0
    check(preview(src, out)['conflicts'] == 0, '12b 无真冲突时 conflicts == 0')

    # 13 源目录零写入
    before13 = tree(src)
    run(src, out)
    check(tree(src) == before13, '13 归档前后源目录完全一致（不写任何标记文件）')

    # 14 续跑幂等：同一 task-id 再跑一次，台账不重复增长、输出目录无新文件
    n_before = core.ledger_stats()['total']
    out_before = tree(out, skip={'log'})
    st14, _ = run(src, out, tid=tid1)
    n_after = core.ledger_stats()['total']
    check(n_after == n_before, '14 断点续跑不重复写台账（%d → %d）' % (n_before, n_after))
    check(tree(out, skip={'log'}) == out_before, '14b 续跑不产生新副本（success 为累计值，故按输出目录比对）')

    # 15 full 哈希模式可用
    o15 = opts(dup_hash='full')
    st15, _ = run(src, out, o15)
    check(st15['success'] == 0 and st15['skipped_dup'] == 3, '15 全文件哈希模式同样判为已归档')

    # 16 预览不写盘（不改源、不产生目标文件）
    out3 = os.path.join(TMP, 'out3')
    preview(src, out3)
    check(not os.path.exists(out3), '16 预览不创建输出目录/文件')

    print('\nSELFTEST_DUPGUARD_OK  checks=%d' % ok_n)
    return 0


if __name__ == '__main__':
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(rc)
