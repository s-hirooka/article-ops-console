"""Eyecatch (featured-image) rendering — cloud port of scratchpad/eyecatch_style.py.

The only change from the local version is the font source: instead of
``C:/Windows/Fonts/YuGoth*.ttc`` (Windows-only, non-redistributable) this uses
**Noto Sans JP** (SIL OFL 1.1, bundled at ``app/assets/fonts/``). The variable
font's Weight axis covers every weight the banners need.

Back-compat: ``font("YuGothB.ttc", 66)`` still works — the old Yu Gothic file
names are aliased to Noto weights, so the existing ``make_eyecatch_*_v2.py``
scripts run unchanged against this module.

Nothing here touches the filesystem for output: ``save_png()`` returns PNG
bytes, so it works on Render's ephemeral disk.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Canvas size. Scripts override via ``import eyecatch as es; es.W, es.H = 1376, 768``
# before calling new_canvas(), exactly as with the old module.
W, H = 1536, 1024

_BUNDLED_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT_DIR = Path(os.environ.get("EYECATCH_FONT_DIR", _BUNDLED_FONT_DIR))
_VF_FILE = "NotoSansJP-VF.ttf"

# logical name / legacy Yu Gothic file name -> Noto Sans JP Weight axis value
_WEIGHT_ALIASES: dict[str, int] = {
    "yugothl.ttc": 300, "yugothr.ttc": 400, "yugothm.ttc": 500, "yugothb.ttc": 700,
    "yugothl": 300, "yugothr": 400, "yugothm": 500, "yugothb": 700,
    "light": 300, "regular": 400, "normal": 400, "medium": 500,
    "semibold": 600, "bold": 700, "black": 900,
}


@lru_cache(maxsize=64)
def _load(weight: int, size: int) -> ImageFont.FreeTypeFont:
    fnt = ImageFont.truetype(str(FONT_DIR / _VF_FILE), size)
    try:
        fnt.set_variation_by_axes([max(100, min(900, int(weight)))])
    except Exception:
        pass
    return fnt


def font(name, size: int) -> ImageFont.FreeTypeFont:
    """Return a Noto Sans JP face at the requested weight.

    ``name`` may be an int weight (100-900), a logical name ("bold", "medium",
    "regular"), or a legacy Yu Gothic file name ("YuGothB.ttc"). Unknown names
    fall back to Regular (400).
    """
    if isinstance(name, (int, float)):
        weight = int(name)
    else:
        key = str(name).strip().lower()
        weight = _WEIGHT_ALIASES.get(key, 400)
    return _load(weight, int(size))


def new_canvas(bg_top, bg_bottom) -> Image.Image:
    """Vertical gradient background, RGBA, ready for compositing."""
    top = Image.new("RGBA", (1, H), (*bg_top, 255))
    px = top.load()
    for y in range(H):
        t = y / H
        r = int(bg_top[0] + (bg_bottom[0] - bg_top[0]) * t)
        g = int(bg_top[1] + (bg_bottom[1] - bg_top[1]) * t)
        b = int(bg_top[2] + (bg_bottom[2] - bg_top[2]) * t)
        px[0, y] = (r, g, b, 255)
    return top.resize((W, H))


def add_blob(canvas, cx, cy, r, color, alpha=70, blur=60):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(layer)


def shadow_for(canvas, draw_fn, offset=(10, 18), blur=20, alpha=80, color=(20, 16, 12)):
    """draw_fn(draw) draws an opaque silhouette; we take its alpha mask,
    recolor+offset+blur it, and composite it onto canvas as a shadow.
    Call this BEFORE drawing the real shape on top."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    draw_fn(d)
    mask = layer.split()[3]
    solid = Image.new("RGBA", canvas.size, (*color, 0))
    solid.putalpha(mask.point(lambda a: alpha if a > 0 else 0))
    shifted = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shifted.paste(solid, offset, solid)
    shifted = shifted.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(shifted)


def bevel_rounded_rect(canvas, box, radius, base_color, highlight_color,
                       outline=None, width=4, highlight_alpha=100):
    """Base fill (opaque) + a soft lighter highlight band across the top."""
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius=radius, fill=base_color, outline=outline, width=width)
    x0, y0, x1, y1 = box
    hl = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    hld = ImageDraw.Draw(hl)
    inset = width + 3
    hld.rounded_rectangle(
        [x0 + inset, y0 + inset, x1 - inset, y0 + (y1 - y0) * 0.4],
        radius=max(radius - inset, 2), fill=(*highlight_color, highlight_alpha),
    )
    canvas.alpha_composite(hl)


def bevel_ellipse(canvas, box, base_color, highlight_color, outline=None, width=0, highlight_alpha=110):
    draw = ImageDraw.Draw(canvas)
    draw.ellipse(box, fill=base_color, outline=outline, width=width)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    hl = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    hld = ImageDraw.Draw(hl)
    hld.ellipse([x0 + w * 0.15, y0 + h * 0.1, x1 - w * 0.35, y0 + h * 0.55],
                fill=(*highlight_color, highlight_alpha))
    canvas.alpha_composite(hl)


def badge_pill(canvas, xy, text, fnt, fg, bg, pad_x=24, pad_y=13):
    draw = ImageDraw.Draw(canvas)
    x, y = xy
    tb = draw.textbbox((0, 0), text, font=fnt)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    box = [x, y, x + tw + pad_x * 2, y + th + pad_y * 2]
    draw.rounded_rectangle(box, radius=(th + pad_y * 2) // 2, fill=bg)
    draw.text((x + pad_x, y + pad_y - tb[1]), text, font=fnt, fill=fg)
    return box


def save_png(canvas: Image.Image) -> bytes:
    """Flatten to opaque RGB and return PNG bytes (no disk write)."""
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
