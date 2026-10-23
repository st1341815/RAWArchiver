#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从源图生成 Windows .ico（多尺寸）。

用法：python make_icon.py <源图> <输出.ico>
"""
import sys


def main():
    if len(sys.argv) != 3:
        print("用法: make_icon.py <源图> <输出.ico>", file=sys.stderr)
        return 1
    src, out = sys.argv[1], sys.argv[2]
    from PIL import Image
    im = Image.open(src)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    w, h = im.size
    side = min(w, h)
    if w != h:
        left, top = (w - side) // 2, (h - side) // 2
        im = im.crop((left, top, left + side, top + side))
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    im.save(out, format="ICO", sizes=sizes)
    print("ico -> %s（%d 个尺寸）" % (out, len(sizes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
