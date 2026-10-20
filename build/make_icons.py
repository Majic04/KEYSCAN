"""Génère l'icône de KeyScan (lentille bleu → cyan → vert pastel) aux formats PNG, .icns (Mac) et .ico (Windows)."""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
N = 1024


def lerp(a, b, t):
    return a + (b - a) * t


def icon(n=N):
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) / n
    # fond : carré arrondi (« squircle ») blanc bleuté, léger dégradé vertical
    bg = np.zeros((n, n, 4), np.float32)
    top, bot = np.array([246, 251, 255]), np.array([221, 238, 250])
    bg[..., :3] = top + (bot - top) * yy[..., None]
    bg[..., 3] = 255
    mask = Image.new("L", (n, n), 0)
    m = int(n * 0.09)
    ImageDraw.Draw(mask).rounded_rectangle([m, m, n - m, n - m], radius=int(n * 0.2), fill=255)
    base = Image.fromarray(bg.astype(np.uint8), "RGBA")
    base.putalpha(mask)
    # ombre portée douce
    shadow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([m, m + n * 0.015, n - m, n - m + n * 0.015], radius=int(n * 0.2), fill=(20, 60, 110, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(n * 0.02))
    out = Image.alpha_composite(shadow, base)
    # lentille : dégradé conique bleu → cyan → vert pastel → bleu
    cx = cy = 0.5
    ang = (np.degrees(np.arctan2(yy - cy, xx - cx)) + 90 + 200) % 360 / 360
    stops = [(0, (47, 123, 245)), (0.38, (34, 195, 214)), (0.68, (143, 221, 180)), (1, (47, 123, 245))]
    col = np.zeros((n, n, 3), np.float32)
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        sel = (ang >= t0) & (ang <= t1)
        t = ((ang - t0) / (t1 - t0))[sel][:, None]
        col[sel] = np.array(c0) + (np.array(c1) - np.array(c0)) * t
    r = np.hypot(xx - cx, yy - cy)
    R = 0.27
    lens = np.zeros((n, n, 4), np.float32)
    lens[..., :3] = col
    lens[..., 3] = np.clip((R - r) * n * 1.5, 0, 1) * 255
    # reflet spéculaire en haut à gauche
    hl = np.exp(-(((xx - 0.42) ** 2) + ((yy - 0.38) ** 2)) / (2 * 0.045 ** 2))
    lens[..., :3] = lens[..., :3] * (1 - 0.85 * hl[..., None]) + 255 * 0.85 * hl[..., None]
    # liseré lumineux
    rim = np.exp(-((r - R + 0.006) ** 2) / (2 * 0.004 ** 2)) * (r < R)
    lens[..., :3] = lens[..., :3] * (1 - 0.35 * rim[..., None]) + 255 * 0.35 * rim[..., None]
    lens_img = Image.fromarray(lens.astype(np.uint8), "RGBA")
    glow = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([n * (0.5 - R), n * (0.5 - R + 0.03), n * (0.5 + R), n * (0.5 + R + 0.03)], fill=(34, 160, 214, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(n * 0.035))
    out = Image.alpha_composite(out, glow)
    return Image.alpha_composite(out, lens_img)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    img = icon()
    img.save(os.path.join(OUT, "keyscan.png"))
    img.save(os.path.join(OUT, "keyscan.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(os.path.join(OUT, "keyscan.icns"))
    print("icônes :", sorted(os.listdir(OUT)))
