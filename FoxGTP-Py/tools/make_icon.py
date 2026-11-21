"""Generate the application icon (assets/foxgtp.ico) without external assets."""

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "assets", "foxgtp.ico")


def make_icon(size=256):
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # rounded dark background
    radius = int(size * 0.22)
    draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius,
                           fill=(11, 18, 32, 255))
    draw.rounded_rectangle([(2, 2), (size - 3, size - 3)], radius=radius,
                           outline=(53, 224, 208, 255), width=max(2, size // 80))

    # fox ears (two triangles)
    cx = size / 2
    ear = size * 0.20
    draw.polygon([(cx - size * 0.30, size * 0.34), (cx - size * 0.12, size * 0.16),
                  (cx - size * 0.05, size * 0.40)], fill=(242, 140, 70, 255))
    draw.polygon([(cx + size * 0.30, size * 0.34), (cx + size * 0.12, size * 0.16),
                  (cx + size * 0.05, size * 0.40)], fill=(242, 140, 70, 255))

    # fox face (rounded triangle-ish)
    draw.ellipse([(cx - ear * 1.5, size * 0.36), (cx + ear * 1.5, size * 0.70)],
                 fill=(242, 160, 90, 255))
    draw.polygon([(cx - ear * 1.5, size * 0.52), (cx, size * 0.76),
                  (cx + ear * 1.5, size * 0.52)], fill=(242, 160, 90, 255))

    # eyes
    eye = max(2, int(size * 0.026))
    draw.ellipse([(cx - size * 0.10 - eye, size * 0.50 - eye),
                  (cx - size * 0.10 + eye, size * 0.50 + eye)], fill=(16, 24, 40, 255))
    draw.ellipse([(cx + size * 0.10 - eye, size * 0.50 - eye),
                  (cx + size * 0.10 + eye, size * 0.50 + eye)], fill=(16, 24, 40, 255))

    # a Go stone in the mouth area
    stone_r = size * 0.075
    draw.ellipse([(cx - stone_r, size * 0.62 - stone_r),
                  (cx + stone_r, size * 0.62 + stone_r)], fill=(242, 246, 255, 255))
    draw.ellipse([(cx - stone_r * 0.55, size * 0.62 - stone_r * 0.55),
                  (cx + stone_r * 0.55, size * 0.62 + stone_r * 0.55)],
                 fill=(220, 230, 245, 255))
    return image


def make_arrows():
    """Small up/down triangles used by the spin box stylesheet."""
    color = (124, 139, 163, 255)
    for name, points in (
        ("arrow_up.png", [(1, 6), (9, 6), (5, 1)]),
        ("arrow_down.png", [(1, 1), (9, 1), (5, 6)]),
    ):
        image = Image.new("RGBA", (10, 7), (0, 0, 0, 0))
        ImageDraw.Draw(image).polygon(points, fill=color)
        image.save(os.path.join(HERE, "assets", name))


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    base = make_icon(256)
    base.save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    base.save(os.path.join(HERE, "assets", "foxgtp.png"))
    make_arrows()
    print("wrote", OUT, "+ arrows")


if __name__ == "__main__":
    main()
