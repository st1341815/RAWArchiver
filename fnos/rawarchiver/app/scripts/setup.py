#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAW 归档 —— 依赖安装
优先使用包内离线 wheels（vendor/wheels），无网络时不至于卡住。
用法：python3 scripts/setup.py [--system]
"""
import os, sys, subprocess, sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / "agent" / "venv"
WHEELS = ROOT / "vendor" / "wheels"
REQ = ["exifread>=3.0", "Pillow>=10.0"]

def run(cmd):
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd)

def main():
    use_system = "--system" in sys.argv
    pip = [sys.executable, "-m", "pip"]
    if not use_system:
        if not VENV.exists():
            print("创建虚拟环境:", VENV)
            if run([sys.executable, "-m", "venv", str(VENV)]) != 0:
                print("venv 创建失败，回退 --system 安装")
                return main_system()
        pip = [str(VENV / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip"))]
    args = pip + ["install", "--disable-pip-version-check"]
    if WHEELS.exists() and any(WHEELS.iterdir()):
        print("使用离线 wheels:", WHEELS)
        args += ["--no-index", "--find-links", str(WHEELS)]
    args += REQ
    rc = run(args)
    if rc != 0 and WHEELS.exists():
        print("离线安装失败，尝试在线安装 ...")
        rc = run(pip + ["install", "--disable-pip-version-check"] + REQ)
    print("依赖安装结果:", "OK" if rc == 0 else "FAILED")
    return rc

def main_system():
    rc = run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check"] + REQ)
    return rc

if __name__ == "__main__":
    sys.exit(main())
