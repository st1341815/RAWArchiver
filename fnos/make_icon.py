#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用一张方形源图生成 RAW 归档 fnOS 包所需的全部图标文件。

用法：
    python3 make_icon.py [源图路径]

源图默认取本脚本同目录下的 icon-source.png。
输出（覆盖）：
    rawarchiver/ICON.PNG                 64x64   包根小图标（应用中心）
    rawarchiver/ICON_256.PNG            256x256  包根大图标
    rawarchiver/app/ui/images/icon_64.png  64x64   桌面/快捷图标
    rawarchiver/app/ui/images/icon_256.png 256x256 桌面/快捷图标

非正方形源图按中心裁成正方形；缩放用 Lanczos。
"""
import os
import sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "rawarchiver")
DEFAULT_SRC = os.path.join(HERE, "icon-source.png")

OUTPUTS = [
    (64,  os.path.join(PKG, "ICON.PNG")),
    (256, os.path.join(PKG, "ICON_256.PNG")),
    (64,  os.path.join(PKG, "app", "ui", "images", "icon_64.png")),
    (256, os.path.join(PKG, "app", "ui", "images", "icon_256.png")),
]


def square(im):
    w, h = im.size
    if w == h:
        return im
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    return im.crop((left, top, left + s, top + s))


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    im = square(Image.open(src).convert("RGBA"))
    print("source", src, "->", im.size, im.mode)
    for size, out in OUTPUTS:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        im.resize((size, size), Image.LANCZOS).save(out)
        print("icon", size, "->", out)
    print("done")


if __name__ == "__main__":
    main()
