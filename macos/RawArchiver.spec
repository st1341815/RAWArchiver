# -*- mode: python ; coding: utf-8 -*-
# RAW 归档 macOS 应用打包配置（PyInstaller onedir + BUNDLE .app）
#
# 结构（onedir）：
#   RawArchiver.app/Contents/MacOS/RawArchiver      ← 入口（GUI；带参数 = CLI 转发）
#   RawArchiver.app/Contents/Resources/www/          ← 前端（与 fnOS 版同一份 index.html）
#   RawArchiver.app/Contents/Resources/scripts/      ← raw_archiver.py（核心，运行时动态 import）
#   RawArchiver.app/Contents/Resources/vendor/exiftool/ ← ExifTool（perl 脚本 + lib，走系统 perl）
#
# 关键点：
#   · core（raw_archiver.py）以**数据文件**形态打进 Resources，运行时经 sys.path 动态
#     import——它的 __file__ 路径逻辑（找 vendor/exiftool、state_root 回落）保持与
#     fnOS 版完全一致，核心脚本零改动。
#   · exifread / Pillow 是 core 的运行时 import，PyInstaller 静态分析看不到，
#     必须在 hiddenimports 里显式声明，否则打包后 EXIF 解析静默降级。
#   · console=False：双击 .app 不弹终端；worker（归档子进程）的 stdout 由
#     server 端 subprocess PIPE 提供，不受 windowed 影响。

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

a = Analysis(
    ['app/main_mac.py'],
    pathex=['app'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # 核心脚本的运行时 import（动态 import 静态分析不可见）
        'exifread',
        'PIL',
        'PIL.Image',
        # pywebview macOS 后端（Cocoa / WKWebView）
        'pywebview',
        'pywebview.platforms.cocoa',
        'pywebview.js',
        'pywebview.util',
        'pywebview.window',
        'Foundation',
        'AppKit',
        'WebKit',
        'Quartz',
        'objc',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'pytest'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RawArchiver',
    debug=False,
    bootloader_tgz_assets=None,
    strip=False,
    upx=False,
    console=False,          # 双击不弹终端；CLI 输出走 subprocess PIPE
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',    # Apple Silicon（M 系列）
    codesign_identity='-',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='RawArchiver',
)

bundle = BUNDLE(
    coll,
    exe,
    name='RawArchiver.app',
    icon='build/RawArchiver.icns',
    bundle_identifier='com.uncle13.rawarchiver',
    version=VERSION,
    info_plist={
        'CFBundleName': 'RawArchiver',
        'CFBundleDisplayName': 'RAW 归档',
        'CFBundleShortVersionString': VERSION,
        'CFBundleGetInfoString': 'RAW 归档 %s — 按 EXIF 拍摄日期归档相机照片/视频' % VERSION,
        'LSMinimumSystemVersion': '11.0',
        'NSHighResolutionCapable': True,
        'NSAppTransportSecurity': {
            # 本机回环 HTTP（pywebview 窗口加载 http://127.0.0.1:<port>）
            'NSAllowsLocalNetworking': True,
        },
    },
)
