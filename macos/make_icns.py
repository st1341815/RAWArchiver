#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从源图生成 macOS iconset 目录（各尺寸 PNG），随后由 iconutil 合成 .icns。

用法：python3 make_icns.py <源图> <输出.iconset 目录>
"""
import os
import sys


def main():
    if len(sys.argv) != 3:
        print("用法: make_icns.py <源图> <输出.iconset>", file=sys.stderr)
        return 1
    src, outdir = sys.argv[1], sys.argv[2]
    from PIL import Image
    im = Image.open(src)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    w, h = im.size
    side = min(w, h)
    if w != h:  # 非正方 → 中心裁方
        left, top = (w - side) // 2, (h - side) // 2
        im = im.crop((left, top, left + side, top + side))

    os.makedirs(outdir, exist_ok=True)
    # iconset 规范尺寸（px）：文件名 → 实际像素
    sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, px in sizes.items():
        im.resize((px, px), Image.LANCZOS).save(os.path.join(outdir, name))
    print("iconset -> %s（%d 个尺寸）" % (outdir, len(sizes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
