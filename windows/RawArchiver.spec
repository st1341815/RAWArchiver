# -*- mode: python ; coding: utf-8 -*-
# RAW 归档 Windows 应用打包配置（PyInstaller onedir + 双 exe）
#
# 为什么双 exe：
#   · RawArchiver.exe（console=False）＝ GUI 入口（双击不弹黑窗）
#   · RawArchiver-cli.exe（console=True）＝ 归档 worker / 命令行入口
#   在 Windows 上 console=False 的程序 sys.stdout 为 None，core 的 print 会崩；
#   归档日志依赖 print → stdout → <输出目录>/log/，故 worker 必须用 console=True 的 cli exe。
#   两者共享同一份依赖（MERGE 去重），打进同一个 dist/RawArchiver/ 目录。
#
# 结构与 macOS 版一致：core/前端/exiftool 以数据文件进 _internal/，
# 运行时动态 import，核心脚本零改动。

import os

VERSION = "1.0.18"

datas = [
    ('app/scripts/raw_archiver.py', 'scripts'),
    ('app/www/index.html', 'www'),
    ('app/www/auth-callback.html', 'www'),
]
if os.path.isdir('app/vendor/exiftool'):
    datas.append(('app/vendor/exiftool', 'vendor/exiftool'))
else:
    print('WARNING: app/vendor/exiftool 不存在，ExifTool 不会打进包（视频日期会退化）')

# exifread / Pillow 是 core 的运行时 import（动态 import 静态分析看不到），必须显式声明。
hiddenimports = [
    'exifread',
    'PIL',
    'PIL.Image',
    # pywebview EdgeChromium 后端（WebView2，Win11 自带）
    'pywebview',
    'pywebview.platforms.edgechromium',
    'pywebview.js',
    'pywebview.util',
    'webview',
]

a_gui = Analysis(
    ['app/main_win.py'],
    pathex=['app'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['tkinter', 'pytest'],
    noarchive=False,
)

# CLI 分析：datas 复用 a_gui 的（同一 COLLECT 目录），只保留 core 需要的依赖
a_cli = Analysis(
    ['app/main_win.py'],
    pathex=['app'],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    excludes=['tkinter', 'pytest'],
    noarchive=False,
)

# 去重公共 binaries，避免 COLLECT 冲突
MERGE((a_gui, 'gui', 'gui'), (a_cli, 'cli', 'cli'))

pyz_gui = PYZ(a_gui.pure)
pyz_cli = PYZ(a_cli.pure)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name='RawArchiver',
    debug=False,
    strip=False,
    upx=False,
    console=False,                    # GUI：双击不弹黑窗
    icon='build/RawArchiver.ico',
)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name='RawArchiver-cli',
    debug=False,
    strip=False,
    upx=False,
    console=True,                     # worker：需要正常 stdout 输出日志
)

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    name='RawArchiver',
    upx=False,
)
