"""Deterministic eyecatch banner -> PNG bytes.

Shared by the article pipeline (size/preview) and the publish step (upload).
Given the same (title, style) it produces the same image, so a draft can be
re-rendered at publish time without stashing the bytes.

``style`` keys (from the domain's ``eyecatch_style`` prompt component):
  preset : "warm_flat" (comfortablelivinglab) | "navy_check" (lifehouse2026)
  width, height : canvas size
  badge  : small category label (optional)
"""
from __future__ import annotations

from PIL import ImageDraw

from app.integrations import eyecatch as es

_PRESETS = {
    "warm_flat": {
        "bg_top": (251, 247, 240), "bg_bottom": (232, 222, 206),
        "ink": (52, 44, 34), "accent": (222, 140, 96), "accent_hi": (245, 190, 160),
        "sub": (112, 100, 86),
    },
    "navy_check": {
        "bg_top": (235, 242, 250), "bg_bottom": (210, 224, 242),
        "ink": (30, 58, 95), "accent": (58, 110, 165), "accent_hi": (120, 164, 205),
        "sub": (70, 90, 120),
    },
}


def _wrap(title: str, limit: int) -> list[str]:
    lines, cur = [], ""
    for ch in title:
        cur += ch
        if len(cur) >= limit:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    return lines[:3]


def render_banner(title: str, style: dict | None = None) -> bytes:
    style = style or {}
    pal = _PRESETS.get(str(style.get("preset", "warm_flat")), _PRESETS["warm_flat"])
    es.W = int(style.get("width", 1536))
    es.H = int(style.get("height", 1024))

    canvas = es.new_canvas(pal["bg_top"], pal["bg_bottom"])
    draw = ImageDraw.Draw(canvas)

    es.add_blob(canvas, int(es.W * 0.86), int(es.H * 0.12), 260, pal["accent"], alpha=45, blur=90)
    es.add_blob(canvas, int(es.W * 0.16), int(es.H * 0.85), 300, pal["ink"], alpha=30, blur=100)

    badge = style.get("badge")
    tx, ty = 96, int(es.H * 0.18)
    if badge:
        box = es.badge_pill(canvas, (tx, ty), str(badge), es.font("bold", 30),
                            (255, 255, 255), pal["ink"])
        ty = box[3] + 40

    big = es.font("bold", 74 if es.W >= 1400 else 56)
    for line in _wrap(title, 11 if es.W >= 1400 else 9):
        draw.text((tx + 3, ty + 3), line, font=big, fill=(0, 0, 0, 40))
        draw.text((tx, ty), line, font=big, fill=pal["ink"])
        ty += int(big.size * 1.35)

    draw.rounded_rectangle([tx, ty + 12, tx + 96, ty + 18], radius=3, fill=pal["accent"])

    # checkmark badge, upper-mid
    bx, by, br = int(es.W * 0.5), int(es.H * 0.30), 40
    es.bevel_ellipse(canvas, [bx - br, by - br, bx + br, by + br], pal["accent"], pal["accent_hi"])
    draw.line([(bx - 16, by), (bx - 3, by + 15), (bx + 18, by - 17)],
              fill=(255, 255, 255), width=8, joint="curve")

    return es.save_png(canvas)
