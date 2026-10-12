import sys, os
from PIL import Image, ImageDraw, ImageFont

PKG = "/vol2/@appshare/octop-native/data/.octop/agents/ZJRYZS/generated/rawarchiver-fpk/rawarchiver"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def make(size, path):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    d.rounded_rectangle([pad, pad, size - 1 - pad, size - 1 - pad],
                        radius=size // 5, fill=(32, 88, 156, 255))
    try:
        font = ImageFont.truetype(FONT, int(size * 0.36))
    except Exception:
        font = ImageFont.load_default()
    txt = "RAW"
    bb = d.textbbox((0, 0), txt, font=font)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((size - w) / 2 - bb[0], (size - h) / 2 - bb[1]), txt, font=font, fill=(255, 255, 255, 255))
    img.save(path)
    print("icon", size, "->", path)


os.makedirs(PKG + "/app/ui/images", exist_ok=True)
make(64,  PKG + "/ICON.PNG")
make(256, PKG + "/ICON_256.PNG")
make(64,  PKG + "/app/ui/images/icon_64.png")
make(256, PKG + "/app/ui/images/icon_256.png")
print("done")
