"""Canvas drawing primitives for one-line diagram symbols.

All draw functions take a Tkinter Canvas and world-space coordinates.
They return a list of canvas item IDs so callers can tag/delete them.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Optional


# ── Colour palette ─────────────────────────────────────────────────────────

COLOUR = {
    "bus":          "#E8E8E8",
    "bus_outline":  "#AAAAAA",
    "line_live":    "#00CC66",
    "line_open":    "#666666",
    "breaker_closed": "#00CC66",
    "breaker_open":   "#FF4444",
    "breaker_outline": "#333333",
    "xfmr_fill":    "#2266AA",
    "xfmr_outline": "#112244",
    "ct_fill":      "#FFAA00",
    "ct_outline":   "#885500",
    "vt_fill":      "#AA44CC",
    "vt_outline":   "#551166",
    "label":        "#DDDDDD",
    "label_dim":    "#888888",
    "selected":     "#FFD700",
    "bg":           "#1A1A2E",
}


# ── Bus bar ─────────────────────────────────────────────────────────────────

def draw_bus(
    canvas: tk.Canvas,
    x: float, y: float,
    length: float = 120,
    label: str = "",
    kv: float = 0.0,
    selected: bool = False,
) -> list[int]:
    ids = []
    half = length / 2
    colour = COLOUR["selected"] if selected else COLOUR["bus_outline"]
    ids.append(canvas.create_rectangle(
        x - half, y - 6, x + half, y + 6,
        fill=COLOUR["bus"], outline=colour, width=2 if selected else 1,
    ))
    if label:
        ids.append(canvas.create_text(
            x, y - 16, text=label,
            fill=COLOUR["label"], font=("Courier", 9, "bold"), anchor="s",
        ))
    if kv:
        ids.append(canvas.create_text(
            x, y + 16, text=f"{kv:.1f} kV",
            fill=COLOUR["label_dim"], font=("Courier", 8), anchor="n",
        ))
    return ids


# ── Wire segment ────────────────────────────────────────────────────────────

def draw_wire(
    canvas: tk.Canvas,
    x1: float, y1: float,
    x2: float, y2: float,
    energised: bool = True,
    width: float = 2.0,
    dash: Optional[tuple] = None,
) -> list[int]:
    colour = COLOUR["line_live"] if energised else COLOUR["line_open"]
    kwargs: dict = {"fill": colour, "width": width}
    if dash:
        kwargs["dash"] = dash
    return [canvas.create_line(x1, y1, x2, y2, **kwargs)]


# ── Circuit breaker ─────────────────────────────────────────────────────────

def draw_breaker(
    canvas: tk.Canvas,
    cx: float, cy: float,
    closed: bool = True,
    selected: bool = False,
    size: float = 14,
) -> list[int]:
    ids = []
    half = size / 2
    fill   = COLOUR["breaker_closed"] if closed else COLOUR["bg"]
    border = COLOUR["selected"] if selected else COLOUR["breaker_outline"]
    ids.append(canvas.create_rectangle(
        cx - half, cy - half, cx + half, cy + half,
        fill=fill, outline=border, width=2,
    ))
    if not closed:
        # Draw an X to indicate open
        ids.append(canvas.create_line(
            cx - half + 3, cy - half + 3,
            cx + half - 3, cy + half - 3,
            fill=COLOUR["breaker_open"], width=2,
        ))
        ids.append(canvas.create_line(
            cx + half - 3, cy - half + 3,
            cx - half + 3, cy + half - 3,
            fill=COLOUR["breaker_open"], width=2,
        ))
    return ids


# ── Two-winding transformer ──────────────────────────────────────────────────

def draw_transformer(
    canvas: tk.Canvas,
    cx: float, cy: float,
    selected: bool = False,
    radius: float = 14,
) -> list[int]:
    ids = []
    gap = radius * 0.3
    outline = COLOUR["selected"] if selected else COLOUR["xfmr_outline"]
    for dy in (-gap, gap):
        ids.append(canvas.create_oval(
            cx - radius, cy + dy - radius,
            cx + radius, cy + dy + radius,
            fill=COLOUR["xfmr_fill"], outline=outline, width=2,
        ))
    return ids


# ── Current transformer (CT) ────────────────────────────────────────────────

def draw_ct(
    canvas: tk.Canvas,
    cx: float, cy: float,
    label: str = "",
    selected: bool = False,
    radius: float = 9,
) -> list[int]:
    ids = []
    outline = COLOUR["selected"] if selected else COLOUR["ct_outline"]
    ids.append(canvas.create_oval(
        cx - radius, cy - radius, cx + radius, cy + radius,
        fill=COLOUR["ct_fill"], outline=outline, width=2,
    ))
    # Small dot in centre
    ids.append(canvas.create_oval(
        cx - 2, cy - 2, cx + 2, cy + 2,
        fill=COLOUR["ct_outline"], outline="",
    ))
    if label:
        ids.append(canvas.create_text(
            cx + radius + 4, cy,
            text=label, fill=COLOUR["label_dim"],
            font=("Courier", 7), anchor="w",
        ))
    return ids


# ── Voltage transformer (VT) ────────────────────────────────────────────────

def draw_vt(
    canvas: tk.Canvas,
    cx: float, cy: float,
    label: str = "",
    selected: bool = False,
    size: float = 12,
) -> list[int]:
    ids = []
    outline = COLOUR["selected"] if selected else COLOUR["vt_outline"]
    # Triangle pointing down
    pts = [
        cx,          cy - size,
        cx - size,   cy + size * 0.5,
        cx + size,   cy + size * 0.5,
    ]
    ids.append(canvas.create_polygon(
        *pts, fill=COLOUR["vt_fill"], outline=outline, width=2,
    ))
    if label:
        ids.append(canvas.create_text(
            cx, cy + size + 4, text=label,
            fill=COLOUR["label_dim"], font=("Courier", 7), anchor="n",
        ))
    return ids


# ── Load arrow ───────────────────────────────────────────────────────────────

def draw_load(
    canvas: tk.Canvas,
    cx: float, cy: float,
    label: str = "",
    size: float = 16,
) -> list[int]:
    ids = []
    # Downward arrow
    ids.append(canvas.create_line(
        cx, cy, cx, cy + size,
        fill=COLOUR["line_live"], width=2, arrow=tk.LAST,
        arrowshape=(8, 10, 4),
    ))
    if label:
        ids.append(canvas.create_text(
            cx + 6, cy + size // 2, text=label,
            fill=COLOUR["label_dim"], font=("Courier", 8), anchor="w",
        ))
    return ids
