#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 dist/RawArchiver/ 打成便携 zip（Git for Windows 不带 zip 命令，用 zipfile）。

用法：python make_zip.py <输出.zip>
"""
import os
import sys
import zipfile


def main():
    if len(sys.argv) != 2:
        print("usage: make_zip.py <out.zip>", file=sys.stderr)
        return 1
    out = sys.argv[1]
    src = os.path.join("dist", "RawArchiver")
    if not os.path.isdir(src):
        print("missing dir: %s" % src, file=sys.stderr)
        return 1
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, "dist"))
                n += 1
    print("zip ok: %s (%d files, %d bytes)" % (out, n, os.path.getsize(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
