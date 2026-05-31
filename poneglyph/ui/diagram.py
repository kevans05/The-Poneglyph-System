"""One-line diagram canvas — paint-app style.

Tools:
  Select        — click to select, drag elements
  Bus           — click-drag horizontally to draw a bus bar
  T-Line        — click bus → click bus
  Feeder        — click bus → click empty point (dangling load end)
  Transformer   — click anywhere to place; near a bus = snaps top terminal to it
  Source        — click anywhere to place a grid/generator source (slack)
  Load          — click anywhere to place a load (PQ)
  CT            — click on an existing connection line
  VT            — click on a bus
  Delete        — click any element to remove it

Visual conventions (IEC 60617):
  Bus           — single thick horizontal line, name above, kV below
  T-Line/Feeder — thin line; breaker shown as small filled square
  Transformer   — two coupled coil windings with an iron core between them;
                  winding-connection indicators (wye / delta / zigzag) alongside
  Source        — circle with a sine wave (AC source)
  Load          — downward filled arrow
  CT            — circle around the conductor + secondary lead
  VT            — winding bumps hanging from a bus tap, IEC ground symbol
"""

from __future__ import annotations

import cmath
import math
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable, Optional


# ── Transformer world-space geometry constants ───────────────────────────────
# All in world units so the symbol is correctly proportioned at any zoom level.
# IEC 60617 coupled-coil symbol: two horizontal coil rows (HV above, LV below),
# bumps facing outward (up/down), iron-core horizontal lines between them,
# centre conductor runs vertically top-to-bottom connecting the buses.

XFMR_BR   = 7.0    # winding bump radius (world units)
XFMR_NB   = 3      # bumps per winding
XFMR_CORE = 30.0   # gap between the two coil rows (iron-core region)
XFMR_LEAD = 14.0   # straight lead from terminal to the first coil row
XFMR_IND  = 9.0    # winding-connection indicator glyph size (world units)

_WIND_SPAN = XFMR_NB * 2 * XFMR_BR                    # 42 — horizontal span of each coil
XFMR_HALF  = XFMR_LEAD + XFMR_CORE / 2               # centre → terminal (= 29)

# ── Source / Load geometry ────────────────────────────────────────────────────
SRC_R       = 16.0   # AC source circle radius (world units)
SRC_OFFSET  = SRC_R * 2 + 16   # source centre distance above its bus
LOAD_AH     = 12.0   # load arrowhead height (world units)
LOAD_AW     = 7.0    # load arrowhead half-width (world units)
LOAD_LEAD   = 30.0   # load lead length from bus to arrowhead base


# ── Element data models ──────────────────────────────────────────────────────

@dataclass
class DiagramBus:
    id: str
    name: str
    kv: float
    x1: float
    y: float
    x2: float
    v_solved: Optional[complex] = None   # per-unit voltage phasor after a solve

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    def nearest_tap(self, x: float) -> float:
        return max(self.x1, min(self.x2, x))

    def hit(self, x: float, y: float, tol: float = 8) -> bool:
        return self.x1 - tol <= x <= self.x2 + tol and abs(y - self.y) <= tol


@dataclass
class DiagramConnection:
    """T-line or feeder between buses (or to a free end point)."""
    id: str
    name: str
    kind: str           # "tline" | "feeder"
    from_bus: str
    from_x: float
    to_bus: Optional[str] = None
    to_x: Optional[float] = None
    to_point: Optional[tuple[float, float]] = None
    has_breaker_from: bool = True
    r_pu: float = 0.01
    x_pu: float = 0.10

    def start_point(self, buses: dict[str, DiagramBus]) -> Optional[tuple[float, float]]:
        b = buses.get(self.from_bus)
        return (b.nearest_tap(self.from_x), b.y) if b else None

    def end_point(self, buses: dict[str, DiagramBus]) -> Optional[tuple[float, float]]:
        if self.to_bus:
            b = buses.get(self.to_bus)
            return (b.nearest_tap(self.to_x or b.cx), b.y) if b else None
        return self.to_point


@dataclass
class DiagramTransformer:
    """Standalone transformer component — placed on the canvas, terminals optionally
    snapped to buses."""
    id: str
    name: str
    cx: float           # centre x (world)
    cy: float           # centre y (world) — midpoint between the two windings
    hv_bus: Optional[str] = None    # top terminal bus
    hv_tap_x: float = 0.0
    lv_bus: Optional[str] = None    # bottom terminal bus
    lv_tap_x: float = 0.0
    # Ratings / electrical
    mva: float = 10.0               # power rating (MVA)
    hv_kv: float = 0.0              # nominal HV winding voltage (kV)
    lv_kv: float = 0.0              # nominal LV winding voltage (kV)
    z_pct: float = 10.0             # impedance (%Z on own MVA base)
    tap_changer: str = "None"       # "None" | "LTC" | "DETC"
    r_pu: float = 0.01              # kept for the solver fallback
    x_pu: float = 0.10
    # Winding configuration (IEC 60617)
    hv_winding:  str  = "wye"       # "wye" | "delta" | "zigzag"
    lv_winding:  str  = "delta"
    hv_grounded: bool = True        # neutral grounded (wye/zigzag only)
    lv_grounded: bool = False

    @property
    def top_y(self) -> float:
        return self.cy - XFMR_HALF

    @property
    def bot_y(self) -> float:
        return self.cy + XFMR_HALF

    @property
    def voltage_ratio(self) -> str:
        if self.hv_kv and self.lv_kv:
            return f"{self.hv_kv:g} : {self.lv_kv:g} kV"
        return "—"


@dataclass
class DiagramSource:
    """Grid / generator source. Defines the slack bus when attached to a bus."""
    id: str
    name: str
    cx: float
    cy: float
    bus: Optional[str] = None
    tap_x: float = 0.0
    v_pu: float = 1.0
    angle_deg: float = 0.0
    base_kv: float = 0.0


@dataclass
class DiagramLoad:
    """Constant-power (PQ) load."""
    id: str
    name: str
    cx: float           # arrow-tip x (world)
    cy: float           # arrow-tip y (world)
    bus: Optional[str] = None
    tap_x: float = 0.0
    p_mw: float = 1.0
    q_mvar: float = 0.5


@dataclass
class DiagramCT:
    id: str
    name: str
    connection_id: str
    t: float = 0.5
    ratio: str = "100/1"


@dataclass
class DiagramVT:
    id: str
    name: str
    bus_id: str
    tap_x: float
    ratio: str = "11000/110"


# ── Tool constants ────────────────────────────────────────────────────────────

TOOL_SELECT      = "select"
TOOL_BUS         = "bus"
TOOL_TLINE       = "tline"
TOOL_FEEDER      = "feeder"
TOOL_TRANSFORMER = "transformer"
TOOL_SOURCE      = "source"
TOOL_LOAD        = "load"
TOOL_CT          = "ct"
TOOL_VT          = "vt"
TOOL_DELETE      = "delete"

TOOL_HINTS = {
    TOOL_SELECT:      "Select: click to select; drag a bus, transformer, source or load to move it.",
    TOOL_BUS:         "Bus: click and drag horizontally to draw a bus bar.",
    TOOL_TLINE:       "T-Line: click a source bus, then click a destination bus.",
    TOOL_FEEDER:      "Feeder: click a bus, then click an empty point for the load end.",
    TOOL_TRANSFORMER: "Transformer: click to place. Near a bus → snaps to it automatically.",
    TOOL_SOURCE:      "Power Source: click to place. Near a bus → snaps to it (defines the slack bus).",
    TOOL_LOAD:        "Load: click to place. Near a bus → snaps to it.",
    TOOL_CT:          "Current Transformer: click on an existing line.",
    TOOL_VT:          "Voltage Transformer: click on a bus.",
    TOOL_DELETE:      "Delete: click any element to remove it.",
}

BUS_WIDTH  = 4
LINE_WIDTH = 2
SNAP_TOL   = 16      # pixels for bus hit-tests
XFMR_SNAP  = 32      # pixels of Y tolerance for transformer/source/load bus-snap

# Default voltage-level colour map (kV → hex colour).
# Keys are nominal kV values; _voltage_colour() picks the nearest one.
DEFAULT_VOLT_COLOURS: dict[float, str] = {
    765:  "#8B008B",   # dark magenta
    500:  "#800080",   # purple
    345:  "#0000CD",   # medium blue
    230:  "#008080",   # teal
    138:  "#FF8C00",   # dark orange
    115:  "#FFA500",   # orange
    69:   "#DAA520",   # goldenrod
    34.5: "#8B4513",   # saddle brown
    13.8: "#228B22",   # forest green
    4.16: "#90EE90",   # light green
    0.48: "#808080",   # gray
}


# ── Diagram canvas ────────────────────────────────────────────────────────────

class Diagram(tk.Frame):
    """Paint-app one-line diagram editor."""

    def __init__(
        self,
        parent: tk.Widget,
        on_select: Optional[Callable] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_select = on_select
        self._on_status = on_status

        self._buses:        dict[str, DiagramBus]         = {}
        self._connections:  dict[str, DiagramConnection]  = {}
        self._transformers: dict[str, DiagramTransformer] = {}
        self._sources:      dict[str, DiagramSource]      = {}
        self._loads:        dict[str, DiagramLoad]        = {}
        self._cts:          dict[str, DiagramCT]          = {}
        self._vts:          dict[str, DiagramVT]          = {}

        self._volt_colours: dict[float, str] = dict(DEFAULT_VOLT_COLOURS)

        self._tool = TOOL_SELECT
        self._selection: Optional[tuple[str, str]] = None

        self._scale    = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0

        self._drag_id:        Optional[str]                 = None
        self._drag_kind:      Optional[str]                 = None
        self._drag_origin:    Optional[tuple[float, float]] = None
        self._bus_draw_start: Optional[tuple[float, float]] = None
        self._conn_from_bus:  Optional[str]                 = None
        self._conn_from_x:    float                         = 0.0
        self._pan_start_pt:   Optional[tuple[int, int]]     = None

        self._build()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.canvas = tk.Canvas(self, bg="white", cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-2>",   self._pan_start)
        self.canvas.bind("<B2-Motion>",       self._pan_drag)
        self.canvas.bind("<ButtonRelease-2>", self._pan_end)
        self.canvas.bind("<ButtonPress-3>",   self._pan_start)
        self.canvas.bind("<B3-Motion>",       self._pan_drag)
        self.canvas.bind("<ButtonRelease-3>", self._pan_end)
        self.canvas.bind("<MouseWheel>",      self._scroll)
        self.canvas.bind("<Button-4>",        self._scroll)
        self.canvas.bind("<Button-5>",        self._scroll)
        self.canvas.bind("<Configure>",       lambda _e: self.redraw())
        self.canvas.bind("<Motion>",          self._on_motion)

    # ── Public API ────────────────────────────────────────────────────────

    def set_tool(self, tool: str) -> None:
        self._tool = tool
        self._conn_from_bus  = None
        self._bus_draw_start = None
        if self._on_status:
            self._on_status(TOOL_HINTS.get(tool, ""))
        cursor = {TOOL_SELECT: "arrow", TOOL_DELETE: "X_cursor"}.get(tool, "crosshair")
        self.canvas.configure(cursor=cursor)
        self.redraw()

    def get_buses(self)        -> dict[str, DiagramBus]:         return self._buses
    def get_connections(self)  -> dict[str, DiagramConnection]:  return self._connections
    def get_transformers(self) -> dict[str, DiagramTransformer]: return self._transformers
    def get_sources(self)      -> dict[str, DiagramSource]:      return self._sources
    def get_loads(self)        -> dict[str, DiagramLoad]:        return self._loads
    def get_cts(self)          -> dict[str, DiagramCT]:          return self._cts
    def get_vts(self)          -> dict[str, DiagramVT]:          return self._vts
    def get_selection(self)    -> Optional[tuple[str, str]]:     return self._selection

    def get_volt_colours(self) -> dict[float, str]:
        return self._volt_colours

    def set_volt_colours(self, mapping: dict[float, str]) -> None:
        self._volt_colours = dict(mapping)
        self.redraw()

    _UNSET_COLOUR = "#333333"   # neutral dark for elements with no voltage level set

    def _voltage_colour(self, kv: float, selected: bool = False) -> str:
        """Return the colour for a given voltage level (kV)."""
        if selected:
            return "#0066CC"
        if not self._volt_colours or kv <= 0:
            return self._UNSET_COLOUR
        nearest = min(self._volt_colours, key=lambda v: abs(v - kv))
        if abs(nearest - kv) / max(nearest, 1) > 0.25:
            return self._UNSET_COLOUR   # no close match — don't mis-colour
        return self._volt_colours[nearest]

    def clear(self) -> None:
        self._buses.clear()
        self._connections.clear()
        self._transformers.clear()
        self._sources.clear()
        self._loads.clear()
        self._cts.clear()
        self._vts.clear()
        self._selection = None
        self.redraw()

    def clear_results(self) -> None:
        """Forget the last power-flow solution (clears voltage annotations)."""
        for bus in self._buses.values():
            bus.v_solved = None
        self.redraw()

    # ── Coordinates ───────────────────────────────────────────────────────

    def _w2s(self, wx: float, wy: float) -> tuple[float, float]:
        return wx * self._scale + self._offset_x, wy * self._scale + self._offset_y

    def _s2w(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self._offset_x) / self._scale, (sy - self._offset_y) / self._scale

    # ── Redraw ────────────────────────────────────────────────────────────

    def redraw(self) -> None:
        self.canvas.delete("all")
        self._draw_grid()
        for conn in self._connections.values():
            self._draw_connection(conn)
        for xfmr in self._transformers.values():
            self._draw_transformer(xfmr)
        for src in self._sources.values():
            self._draw_source(src)
        for ld in self._loads.values():
            self._draw_load(ld)
        for bus in self._buses.values():
            self._draw_bus(bus)
        for ct in self._cts.values():
            self._draw_ct(ct)
        for vt in self._vts.values():
            self._draw_vt(vt)

    def _draw_grid(self) -> None:
        w = self.canvas.winfo_width()  or 800
        h = self.canvas.winfo_height() or 600
        step = 20 * self._scale
        if step < 8:
            return
        x = self._offset_x % step
        while x < w:
            y = self._offset_y % step
            while y < h:
                self.canvas.create_oval(x-1, y-1, x+1, y+1, fill="#DDDDDD", outline="")
                y += step
            x += step

    # ── Bus ───────────────────────────────────────────────────────────────

    def _draw_bus(self, bus: DiagramBus) -> None:
        sx1, sy = self._w2s(bus.x1, bus.y)
        sx2, _  = self._w2s(bus.x2, bus.y)
        sel    = self._selection == ("bus", bus.id)
        colour = self._voltage_colour(bus.kv, selected=sel)
        self.canvas.create_line(sx1, sy, sx2, sy,
                                width=BUS_WIDTH, fill=colour, capstyle=tk.ROUND)
        cx = (sx1 + sx2) / 2
        self.canvas.create_text(cx, sy - 12, text=bus.name,
                                font=("TkDefaultFont", 9, "bold"), fill=colour, anchor="s")
        if bus.kv:
            self.canvas.create_text(cx, sy + 10, text=f"{bus.kv} kV",
                                    font=("TkDefaultFont", 8), fill=colour, anchor="n")
        if bus.v_solved is not None:
            mag = abs(bus.v_solved)
            ang = math.degrees(cmath.phase(bus.v_solved))
            kv_actual = mag * bus.kv if bus.kv else 0.0
            txt = f"{mag:.3f} pu ∠{ang:.1f}°"
            if kv_actual:
                txt += f"  ({kv_actual:.2f} kV)"
            self.canvas.create_text(cx, sy + 24, text=txt,
                                    font=("TkDefaultFont", 8, "bold"),
                                    fill="#118811", anchor="n")

    # ── Connections (T-line / feeder) ─────────────────────────────────────

    def _draw_connection(self, conn: DiagramConnection) -> None:
        start = conn.start_point(self._buses)
        end   = conn.end_point(self._buses)
        if start is None or end is None:
            return
        x1, y1 = self._w2s(*start)
        x2, y2 = self._w2s(*end)
        sel    = self._selection == ("conn", conn.id)
        from_bus = self._buses.get(conn.from_bus)
        kv = from_bus.kv if from_bus else 0.0
        colour = self._voltage_colour(kv, selected=sel)

        self.canvas.create_line(x1, y1, x2, y2, width=LINE_WIDTH, fill=colour)

        if conn.has_breaker_from:
            self._draw_breaker(x1, y1, x2, y2, t=0.15, colour=colour)

        if conn.kind == "feeder":
            self._draw_load_triangle(x2, y2, colour)

        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        self.canvas.create_text(mx + 6, my, text=conn.name,
                                font=("TkDefaultFont", 8), fill="#444444", anchor="w")

    def _draw_breaker(self, x1, y1, x2, y2, t: float, colour: str) -> None:
        bx = x1 + (x2 - x1) * t
        by = y1 + (y2 - y1) * t
        h  = 5 * self._scale
        self.canvas.create_rectangle(bx - h, by - h, bx + h, by + h,
                                     fill=colour, outline=colour)

    def _draw_load_triangle(self, x: float, y: float, colour: str) -> None:
        s = 10 * self._scale
        self.canvas.create_polygon(x, y, x - s, y + s * 1.6, x + s, y + s * 1.6,
                                   fill="white", outline=colour, width=LINE_WIDTH)

    # ── Transformer (standalone, world-space IEC coupled-coil symbol) ─────

    def _draw_transformer(self, xfmr: DiagramTransformer) -> None:
        sel      = self._selection == ("transformer", xfmr.id)
        hv_col   = self._voltage_colour(xfmr.hv_kv, selected=sel)
        lv_col   = self._voltage_colour(xfmr.lv_kv, selected=sel)
        core_col = "#0066CC" if sel else self._UNSET_COLOUR
        r    = XFMR_BR
        n    = XFMR_NB
        span = _WIND_SPAN   # horizontal span of each coil row

        hv_y   = xfmr.cy - XFMR_CORE / 2
        lv_y   = xfmr.cy + XFMR_CORE / 2
        x_left = xfmr.cx - span / 2

        # ── HV terminal lead (bus → top of centre conductor) ─────────────
        ct_sx, ct_sy = self._w2s(xfmr.cx, hv_y)   # outer edge of HV coil spine
        if xfmr.hv_bus and xfmr.hv_bus in self._buses:
            bus = self._buses[xfmr.hv_bus]
            bsx, bsy = self._w2s(bus.nearest_tap(xfmr.hv_tap_x), bus.y)
            self.canvas.create_line(bsx, bsy, ct_sx, ct_sy,
                                    fill=hv_col, width=LINE_WIDTH)
        else:
            t_sx, t_sy = self._w2s(xfmr.cx, xfmr.top_y)
            self.canvas.create_line(t_sx, t_sy, ct_sx, ct_sy,
                                    fill=hv_col, width=LINE_WIDTH)
            self._terminal_dot(t_sx, t_sy, hv_col)

        # ── LV terminal lead (outer edge of LV coil spine → bus) ──────────
        cb_sx, cb_sy = self._w2s(xfmr.cx, lv_y)   # outer edge of LV coil spine
        if xfmr.lv_bus and xfmr.lv_bus in self._buses:
            bus = self._buses[xfmr.lv_bus]
            bsx, bsy = self._w2s(bus.nearest_tap(xfmr.lv_tap_x), bus.y)
            self.canvas.create_line(cb_sx, cb_sy, bsx, bsy,
                                    fill=lv_col, width=LINE_WIDTH)
        else:
            b_sx, b_sy = self._w2s(xfmr.cx, xfmr.bot_y)
            self.canvas.create_line(cb_sx, cb_sy, b_sx, b_sy,
                                    fill=lv_col, width=LINE_WIDTH)
            self._terminal_dot(b_sx, b_sy, lv_col)

        # ── Centre conductor: HV colour top half, LV colour bottom half ──────
        cm_sx, cm_sy = self._w2s(xfmr.cx, xfmr.cy)
        self.canvas.create_line(ct_sx, ct_sy, cm_sx, cm_sy, fill=hv_col, width=LINE_WIDTH)
        self.canvas.create_line(cm_sx, cm_sy, cb_sx, cb_sy, fill=lv_col, width=LINE_WIDTH)

        # ── HV coil row (bumps inward / downward) ─────────────────────────
        self._draw_coil_h(x_left, hv_y, n, r, bulge_up=False, colour=hv_col)

        # ── LV coil row (bumps inward / upward) ───────────────────────────
        self._draw_coil_h(x_left, lv_y, n, r, bulge_up=True, colour=lv_col)

        # ── Iron core: two horizontal lines in the gap ────────────────────
        for off in (-2.5, 2.5):
            ic_l_sx, ic_l_sy = self._w2s(xfmr.cx - span / 2, xfmr.cy + off)
            ic_r_sx, ic_r_sy = self._w2s(xfmr.cx + span / 2, xfmr.cy + off)
            self.canvas.create_line(ic_l_sx, ic_l_sy, ic_r_sx, ic_r_sy,
                                    fill=core_col, width=LINE_WIDTH + 1)

        # ── Winding indicators + kV labels to the right of each coil row ──
        ind_x = xfmr.cx + span / 2 + XFMR_IND + 16
        self._draw_winding_indicator(ind_x, hv_y, xfmr.hv_winding, xfmr.hv_grounded, hv_col)
        self._draw_winding_indicator(ind_x, lv_y, xfmr.lv_winding, xfmr.lv_grounded, lv_col)

        kv_x = xfmr.cx - span / 2 - 6   # kV labels on the left side
        if xfmr.hv_kv:
            kv_sx, kv_sy = self._w2s(kv_x, hv_y)
            self.canvas.create_text(kv_sx, kv_sy, text=f"{xfmr.hv_kv:g} kV",
                                    font=("TkDefaultFont", 8, "bold"),
                                    fill=hv_col, anchor="e")
        if xfmr.lv_kv:
            kv_sx, kv_sy = self._w2s(kv_x, lv_y)
            self.canvas.create_text(kv_sx, kv_sy, text=f"{xfmr.lv_kv:g} kV",
                                    font=("TkDefaultFont", 8, "bold"),
                                    fill=lv_col, anchor="e")

        # ── Label (name + MVA, centred to the left) ───────────────────────
        label = xfmr.name
        if xfmr.mva:
            label += f"\n{xfmr.mva:g} MVA"
        l_sx, l_sy = self._w2s(kv_x, xfmr.cy)
        self.canvas.create_text(l_sx, l_sy, text=label, justify="right",
                                font=("TkDefaultFont", 8), fill="#444444", anchor="e")

    def _terminal_dot(self, sx: float, sy: float, colour: str) -> None:
        rd = max(3, 3 * self._scale)
        self.canvas.create_oval(sx - rd, sy - rd, sx + rd, sy + rd,
                                fill=colour, outline=colour)

    def _draw_coil_h(self, x_left_w: float, cy_w: float, n: int, r: float,
                     bulge_up: bool, colour: str) -> None:
        """Draw a horizontal coil of n half-loop bumps centred on cy_w.

        Bumps face upward (bulge_up=True) or downward, starting at x_left_w.
        """
        N = 18
        sign = -1.0 if bulge_up else 1.0   # up = negative y
        for i in range(n):
            bx = x_left_w + r + i * 2 * r
            pts: list[float] = []
            for j in range(N + 1):
                t  = -math.pi / 2 + math.pi * j / N
                wx = bx + r * math.sin(t)
                wy = cy_w + sign * r * math.cos(t)
                sx, sy = self._w2s(wx, wy)
                pts.extend([sx, sy])
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

    def _draw_coil(self, cx_w: float, y_top_w: float, n: int, r: float,
                   bulge_left: bool, colour: str) -> None:
        """Draw a vertical coil of n half-loop bumps starting at y_top_w."""
        N = 18
        sign = -1.0 if bulge_left else 1.0
        for i in range(n):
            by = y_top_w + r + i * 2 * r
            pts: list[float] = []
            for j in range(N + 1):
                t  = -math.pi / 2 + math.pi * j / N
                wx = cx_w + sign * r * math.cos(t)
                wy = by + r * math.sin(t)
                sx, sy = self._w2s(wx, wy)
                pts.extend([sx, sy])
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

    def _draw_winding_indicator(self, ax_w: float, ay_w: float,
                                wtype: str, grounded: bool, colour: str) -> None:
        """Draw IEC winding-connection indicator (wye / delta / zigzag) at world point."""
        s = XFMR_IND

        if wtype == "wye":
            # Y / star: one arm up, two arms down-left and down-right.
            cx_s, cy_s = self._w2s(ax_w, ay_w)
            for ang in (-math.pi / 2, math.pi / 6, 5 * math.pi / 6):
                ex, ey = self._w2s(ax_w + s * math.cos(ang), ay_w + s * math.sin(ang))
                self.canvas.create_line(cx_s, cy_s, ex, ey, fill=colour, width=LINE_WIDTH)
            if grounded:
                self._draw_ground_stub(ax_w, ay_w, colour)

        elif wtype == "delta":
            # Equilateral triangle, point up.
            pts_w = [(ax_w, ay_w - s * 0.75),
                     (ax_w - s * 0.7, ay_w + s * 0.55),
                     (ax_w + s * 0.7, ay_w + s * 0.55)]
            pts_s: list[float] = []
            for wx, wy in pts_w:
                px, py = self._w2s(wx, wy)
                pts_s.extend([px, py])
            self.canvas.create_polygon(*pts_s, outline=colour, fill="", width=LINE_WIDTH)

        elif wtype == "zigzag":
            # Vertical zigzag (interconnected-star) glyph.
            steps = [(0.0, -1.0), (0.55, -0.5), (-0.55, 0.0), (0.55, 0.5), (0.0, 1.0)]
            pts_s = []
            for fx, fy in steps:
                px, py = self._w2s(ax_w + fx * s, ay_w + fy * s)
                pts_s.extend([px, py])
            self.canvas.create_line(*pts_s, fill=colour, width=LINE_WIDTH)
            if grounded:
                self._draw_ground_stub(ax_w, ay_w, colour)

    def _draw_ground_stub(self, ax_w: float, ay_w: float, colour: str) -> None:
        """Small IEC earth symbol on a short stub to the left of (ax_w, ay_w)."""
        stub = XFMR_IND * 0.9
        x0_sx, x0_sy = self._w2s(ax_w, ay_w)
        end_sx, end_sy = self._w2s(ax_w - stub, ay_w)
        self.canvas.create_line(x0_sx, x0_sy, end_sx, end_sy, fill=colour, width=LINE_WIDTH)
        for k, half in enumerate((5.0, 3.0, 1.5)):
            bx_w = ax_w - stub - k * 2.0
            t_sx, t_sy = self._w2s(bx_w, ay_w - half)
            b_sx, b_sy = self._w2s(bx_w, ay_w + half)
            self.canvas.create_line(t_sx, t_sy, b_sx, b_sy, fill=colour, width=LINE_WIDTH)

    # ── Source (AC source / grid / generator) ─────────────────────────────

    def _draw_source(self, src: DiagramSource) -> None:
        sel    = self._selection == ("source", src.id)
        colour = "#0066CC" if sel else "black"
        rs = SRC_R * self._scale
        csx, csy = self._w2s(src.cx, src.cy)

        # Lead from bottom of circle to bus (or free terminal).
        bot_sx, bot_sy = self._w2s(src.cx, src.cy + SRC_R)
        if src.bus and src.bus in self._buses:
            bus = self._buses[src.bus]
            tsx, tsy = self._w2s(bus.nearest_tap(src.tap_x), bus.y)
            self.canvas.create_line(bot_sx, bot_sy, tsx, tsy, fill=colour, width=LINE_WIDTH)
        else:
            self._terminal_dot(bot_sx, bot_sy, colour)

        self.canvas.create_oval(csx - rs, csy - rs, csx + rs, csy + rs,
                                outline=colour, fill="white", width=LINE_WIDTH)

        # Sine wave inside the circle.
        half = SRC_R * 0.6
        amp  = SRC_R * 0.38
        pts: list[float] = []
        N = 26
        for k in range(N + 1):
            frac = k / N
            wx = src.cx - half + 2 * half * frac
            wy = src.cy - amp * math.sin(2 * math.pi * frac)
            sx, sy = self._w2s(wx, wy)
            pts.extend([sx, sy])
        self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

        lsx, lsy = self._w2s(src.cx + SRC_R + 6, src.cy)
        label = f"{src.name}\n{src.v_pu:g} pu"
        self.canvas.create_text(lsx, lsy, text=label, justify="left",
                                font=("TkDefaultFont", 8), fill="#444444", anchor="w")

    # ── Load (downward filled arrow) ──────────────────────────────────────

    def _draw_load(self, ld: DiagramLoad) -> None:
        sel    = self._selection == ("load", ld.id)
        colour = "#0066CC" if sel else "black"

        base_w = ld.cy - LOAD_AH                 # arrowhead base
        tip_sx, tip_sy   = self._w2s(ld.cx, ld.cy)
        base_sx, base_sy = self._w2s(ld.cx, base_w)

        # Lead from bus (or free terminal) down to the arrowhead base.
        if ld.bus and ld.bus in self._buses:
            bus = self._buses[ld.bus]
            tsx, tsy = self._w2s(bus.nearest_tap(ld.tap_x), bus.y)
            self.canvas.create_line(tsx, tsy, base_sx, base_sy, fill=colour, width=LINE_WIDTH)
        else:
            top_sx, top_sy = self._w2s(ld.cx, base_w - LOAD_LEAD)
            self.canvas.create_line(top_sx, top_sy, base_sx, base_sy, fill=colour, width=LINE_WIDTH)
            self._terminal_dot(top_sx, top_sy, colour)

        aw = LOAD_AW * self._scale
        self.canvas.create_polygon(tip_sx, tip_sy,
                                   base_sx - aw, base_sy,
                                   base_sx + aw, base_sy,
                                   fill=colour, outline=colour)

        lsx, lsy = self._w2s(ld.cx + LOAD_AW + 6, ld.cy - LOAD_AH / 2)
        label = f"{ld.name}\n{ld.p_mw:g} MW / {ld.q_mvar:g} MVAr"
        self.canvas.create_text(lsx, lsy, text=label, justify="left",
                                font=("TkDefaultFont", 8), fill="#444444", anchor="w")

    # ── CT ────────────────────────────────────────────────────────────────

    def _draw_ct(self, ct: DiagramCT) -> None:
        conn = self._connections.get(ct.connection_id)
        if conn is None:
            return
        start = conn.start_point(self._buses)
        end   = conn.end_point(self._buses)
        if start is None or end is None:
            return
        wx1, wy1 = start
        wx2, wy2 = end
        wx = wx1 + (wx2 - wx1) * ct.t
        wy = wy1 + (wy2 - wy1) * ct.t
        sx, sy = self._w2s(wx, wy)

        sel    = self._selection == ("ct", ct.id)
        colour = "#0066CC" if sel else "black"

        r = 10 * self._scale
        self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r,
                                outline=colour, fill="white", width=LINE_WIDTH)

        dx, dy = wx2 - wx1, wy2 - wy1
        length = math.hypot(dx, dy) or 1
        pxn, pyn = -dy / length, dx / length
        lead = r + 10
        ex, ey = sx + pxn * lead, sy + pyn * lead
        self.canvas.create_line(sx, sy, ex, ey, fill=colour, width=LINE_WIDTH)
        self.canvas.create_line(ex - pyn * 5, ey + pxn * 5,
                                ex + pyn * 5, ey - pxn * 5,
                                fill=colour, width=LINE_WIDTH)
        self.canvas.create_text(ex + pxn * 4, ey + pyn * 4,
                                text=ct.name, font=("TkDefaultFont", 8),
                                fill="#444444", anchor="w")

    # ── VT ────────────────────────────────────────────────────────────────

    def _draw_vt(self, vt: DiagramVT) -> None:
        bus = self._buses.get(vt.bus_id)
        if bus is None:
            return
        tap_x = bus.nearest_tap(vt.tap_x)
        sx, sy = self._w2s(tap_x, bus.y)

        sel    = self._selection == ("vt", vt.id)
        colour = "#0066CC" if sel else "black"

        r    = 6 * self._scale
        drop = 12 * self._scale

        self.canvas.create_line(sx, sy, sx, sy + drop, fill=colour, width=LINE_WIDTH)

        winding_top = sy + drop
        n = 3
        N = 16
        for i in range(n):
            by = winding_top + r + i * 2 * r
            pts = []
            for j in range(N + 1):
                t = -math.pi / 2 + math.pi * j / N
                pts.extend([sx + r * math.cos(t), by + r * math.sin(t)])
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

        winding_bot = winding_top + n * 2 * r
        r2 = r * 0.75
        sec_top = winding_bot + r * 0.5
        for i in range(n):
            by = sec_top + r2 + i * 2 * r2
            pts = []
            for j in range(N + 1):
                t = -math.pi / 2 + math.pi * j / N
                pts.extend([sx - r2 * math.cos(t), by + r2 * math.sin(t)])
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill=colour, width=LINE_WIDTH, smooth=True)

        sec_bot = sec_top + n * 2 * r2
        gy = sec_bot + 4 * self._scale
        self.canvas.create_line(sx, sec_bot, sx, gy, fill=colour, width=LINE_WIDTH)
        for k, w in enumerate([10, 6, 3]):
            ws = w * self._scale
            yy = gy + k * 4 * self._scale
            self.canvas.create_line(sx - ws, yy, sx + ws, yy, fill=colour, width=LINE_WIDTH)

        self.canvas.create_text(sx + 14 * self._scale,
                                winding_top + (winding_bot - winding_top) / 2,
                                text=vt.name, font=("TkDefaultFont", 8),
                                fill="#444444", anchor="w")

    # ── Hit testing ───────────────────────────────────────────────────────

    def _hit_bus(self, wx: float, wy: float) -> Optional[str]:
        for bus in self._buses.values():
            if bus.hit(wx, wy, tol=SNAP_TOL / self._scale):
                return bus.id
        return None

    def _snap_bus(self, wx: float, wy: float) -> Optional[str]:
        """Snap for transformer/source/load placement: cursor must be over the bus
        bar (strict X) but with a wide Y tolerance so the user can approach it."""
        tol_y = XFMR_SNAP / self._scale
        for bus in self._buses.values():
            if bus.x1 <= wx <= bus.x2 and abs(wy - bus.y) <= tol_y:
                return bus.id
        return None

    def _hit_connection(self, sx: float, sy: float) -> Optional[str]:
        for conn in self._connections.values():
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start is None or end is None:
                continue
            x1, y1 = self._w2s(*start)
            x2, y2 = self._w2s(*end)
            if _point_to_segment_dist(sx, sy, x1, y1, x2, y2) < 8:
                return conn.id
        return None

    def _hit_transformer(self, wx: float, wy: float) -> Optional[str]:
        tol_x = XFMR_BR * 2 + 4
        tol_y = XFMR_HALF
        for xfmr in self._transformers.values():
            if abs(wx - xfmr.cx) < tol_x and abs(wy - xfmr.cy) < tol_y:
                return xfmr.id
        return None

    def _hit_source(self, wx: float, wy: float) -> Optional[str]:
        for src in self._sources.values():
            if math.hypot(wx - src.cx, wy - src.cy) < SRC_R + 4:
                return src.id
        return None

    def _hit_load(self, wx: float, wy: float) -> Optional[str]:
        for ld in self._loads.values():
            top = ld.cy - LOAD_AH - LOAD_LEAD - 4
            if abs(wx - ld.cx) < LOAD_AW + 6 and top <= wy <= ld.cy + 4:
                return ld.id
        return None

    def _hit_ct(self, sx: float, sy: float) -> Optional[str]:
        for ct in self._cts.values():
            conn = self._connections.get(ct.connection_id)
            if conn is None:
                continue
            start = conn.start_point(self._buses)
            end   = conn.end_point(self._buses)
            if start is None or end is None:
                continue
            wx1, wy1 = start
            wx2, wy2 = end
            wx = wx1 + (wx2 - wx1) * ct.t
            wy = wy1 + (wy2 - wy1) * ct.t
            csx, csy = self._w2s(wx, wy)
            if math.hypot(sx - csx, sy - csy) < 12 * self._scale:
                return ct.id
        return None

    def _hit_vt(self, wx: float, wy: float) -> Optional[str]:
        tol = SNAP_TOL / self._scale
        for vt in self._vts.values():
            bus = self._buses.get(vt.bus_id)
            if bus is None:
                continue
            if abs(bus.nearest_tap(vt.tap_x) - wx) < tol and abs(bus.y - wy) < tol * 2:
                return vt.id
        return None

    # ── Mouse events ──────────────────────────────────────────────────────

    def _on_press(self, event: tk.Event) -> None:
        wx, wy = self._s2w(event.x, event.y)

        if self._tool == TOOL_SELECT:
            xfmr_id = self._hit_transformer(wx, wy)
            src_id  = self._hit_source(wx, wy)
            load_id = self._hit_load(wx, wy)
            ct_id   = self._hit_ct(event.x, event.y)
            vt_id   = self._hit_vt(wx, wy)
            bus_id  = self._hit_bus(wx, wy)
            conn_id = self._hit_connection(event.x, event.y)
            if xfmr_id:
                self._begin_drag("transformer", xfmr_id, wx, wy)
            elif src_id:
                self._begin_drag("source", src_id, wx, wy)
            elif load_id:
                self._begin_drag("load", load_id, wx, wy)
            elif ct_id:
                self._set_selection("ct", ct_id)
            elif vt_id:
                self._set_selection("vt", vt_id)
            elif bus_id:
                self._begin_drag("bus", bus_id, wx, wy)
            elif conn_id:
                self._set_selection("conn", conn_id)
            else:
                self._set_selection(None, None)

        elif self._tool == TOOL_BUS:
            self._bus_draw_start = (wx, wy)

        elif self._tool in (TOOL_TLINE, TOOL_FEEDER):
            bus_id = self._hit_bus(wx, wy)
            if self._conn_from_bus is None:
                if bus_id:
                    self._conn_from_bus = bus_id
                    self._conn_from_x   = wx
                    if self._on_status:
                        self._on_status(
                            f"From '{self._buses[bus_id].name}' — now click the destination."
                        )
            else:
                self._finish_connection(wx, wy, bus_id)

        elif self._tool == TOOL_TRANSFORMER:
            snap_id = self._snap_bus(wx, wy)
            tid = f"XFMR-{len(self._transformers) + 1}"
            if snap_id:
                bus = self._buses[snap_id]
                tap_x = bus.nearest_tap(wx)
                xfmr = DiagramTransformer(
                    id=tid, name=tid,
                    cx=tap_x,
                    cy=bus.y + XFMR_HALF,   # top_y == bus.y: HV terminal on the bus
                    hv_bus=snap_id, hv_tap_x=tap_x,
                    hv_kv=bus.kv or 0.0,
                )
            else:
                xfmr = DiagramTransformer(id=tid, name=tid, cx=wx, cy=wy)
            self._transformers[tid] = xfmr
            self._set_selection("transformer", tid)

        elif self._tool == TOOL_SOURCE:
            snap_id = self._snap_bus(wx, wy)
            sid = f"SRC-{len(self._sources) + 1}"
            if snap_id:
                bus = self._buses[snap_id]
                tap_x = bus.nearest_tap(wx)
                src = DiagramSource(sid, sid, cx=tap_x, cy=bus.y - SRC_OFFSET,
                                    bus=snap_id, tap_x=tap_x, base_kv=bus.kv or 0.0)
            else:
                src = DiagramSource(sid, sid, cx=wx, cy=wy)
            self._sources[sid] = src
            self._set_selection("source", sid)

        elif self._tool == TOOL_LOAD:
            snap_id = self._snap_bus(wx, wy)
            lid = f"LOAD-{len(self._loads) + 1}"
            if snap_id:
                bus = self._buses[snap_id]
                tap_x = bus.nearest_tap(wx)
                ld = DiagramLoad(lid, lid, cx=tap_x,
                                 cy=bus.y + LOAD_LEAD + LOAD_AH,
                                 bus=snap_id, tap_x=tap_x)
            else:
                ld = DiagramLoad(lid, lid, cx=wx, cy=wy)
            self._loads[lid] = ld
            self._set_selection("load", lid)

        elif self._tool == TOOL_CT:
            conn_id = self._hit_connection(event.x, event.y)
            if conn_id:
                conn  = self._connections[conn_id]
                start = conn.start_point(self._buses)
                end   = conn.end_point(self._buses)
                if start and end:
                    wx1, wy1 = start
                    wx2, wy2 = end
                    total = math.hypot(wx2 - wx1, wy2 - wy1) or 1
                    t = max(0.1, min(0.9, math.hypot(wx - wx1, wy - wy1) / total))
                    cid = f"CT-{len(self._cts) + 1}"
                    self._cts[cid] = DiagramCT(cid, cid, conn_id, t)
                    self._set_selection("ct", cid)

        elif self._tool == TOOL_VT:
            bus_id = self._hit_bus(wx, wy)
            if bus_id:
                vid = f"VT-{len(self._vts) + 1}"
                self._vts[vid] = DiagramVT(vid, vid, bus_id, wx)
                self._set_selection("vt", vid)

        elif self._tool == TOOL_DELETE:
            self._delete_at(event, wx, wy)

    def _begin_drag(self, kind: str, elem_id: str, wx: float, wy: float) -> None:
        self._set_selection(kind, elem_id)
        self._drag_id     = elem_id
        self._drag_kind   = kind
        self._drag_origin = (wx, wy)

    def _delete_at(self, event: tk.Event, wx: float, wy: float) -> None:
        xfmr_id = self._hit_transformer(wx, wy)
        src_id  = self._hit_source(wx, wy)
        load_id = self._hit_load(wx, wy)
        ct_id   = self._hit_ct(event.x, event.y)
        vt_id   = self._hit_vt(wx, wy)
        bus_id  = self._hit_bus(wx, wy)
        conn_id = self._hit_connection(event.x, event.y)
        if xfmr_id:
            self._transformers.pop(xfmr_id, None)
            self._set_selection(None, None); self.redraw()
        elif src_id:
            self._sources.pop(src_id, None)
            self._set_selection(None, None); self.redraw()
        elif load_id:
            self._loads.pop(load_id, None)
            self._set_selection(None, None); self.redraw()
        elif ct_id:
            self._cts.pop(ct_id, None)
            self._set_selection(None, None); self.redraw()
        elif vt_id:
            self._vts.pop(vt_id, None)
            self._set_selection(None, None); self.redraw()
        elif bus_id:
            self._delete_bus(bus_id)
        elif conn_id:
            self._delete_connection(conn_id)

    def _on_drag(self, event: tk.Event) -> None:
        wx, wy = self._s2w(event.x, event.y)

        if self._tool == TOOL_SELECT and self._drag_id and self._drag_origin:
            dx = wx - self._drag_origin[0]
            dy = wy - self._drag_origin[1]
            if self._drag_kind == "bus":
                bus = self._buses[self._drag_id]
                bus.x1 += dx;  bus.x2 += dx;  bus.y += dy
            elif self._drag_kind == "transformer":
                xfmr = self._transformers[self._drag_id]
                xfmr.cx += dx;  xfmr.cy += dy
            elif self._drag_kind == "source":
                src = self._sources[self._drag_id]
                src.cx += dx;  src.cy += dy
            elif self._drag_kind == "load":
                ld = self._loads[self._drag_id]
                ld.cx += dx;  ld.cy += dy
            self._drag_origin = (wx, wy)
            self.redraw()

        elif self._tool == TOOL_BUS and self._bus_draw_start:
            self.redraw()
            sx1, sy1 = self._w2s(*self._bus_draw_start)
            self.canvas.create_line(sx1, sy1, event.x, sy1,
                                    width=BUS_WIDTH, fill="#888888", dash=(4, 4))

    def _on_release(self, event: tk.Event) -> None:
        if self._tool == TOOL_BUS and self._bus_draw_start:
            wx, wy = self._s2w(event.x, event.y)
            x1, y0 = self._bus_draw_start
            x2 = wx
            if abs(x2 - x1) > 10 / self._scale:
                bid = f"BUS-{len(self._buses) + 1}"
                self._buses[bid] = DiagramBus(bid, bid, 0.0,
                                              min(x1, x2), y0, max(x1, x2))
                self._set_selection("bus", bid)
            self._bus_draw_start = None
            self.redraw()
        self._drag_id     = None
        self._drag_kind   = None
        self._drag_origin = None

    def _on_motion(self, event: tk.Event) -> None:
        wx, wy = self._s2w(event.x, event.y)

        if self._tool in (TOOL_TLINE, TOOL_FEEDER) and self._conn_from_bus:
            self.redraw()
            bus = self._buses.get(self._conn_from_bus)
            if bus:
                sx, sy = self._w2s(bus.nearest_tap(self._conn_from_x), bus.y)
                self.canvas.create_line(sx, sy, event.x, event.y,
                                        width=LINE_WIDTH, fill="#888888", dash=(4, 4))

        elif self._tool in (TOOL_TRANSFORMER, TOOL_SOURCE, TOOL_LOAD):
            snap_id = self._snap_bus(wx, wy)
            if snap_id:
                self.redraw()
                bus = self._buses[snap_id]
                tap_sx, tap_sy = self._w2s(bus.nearest_tap(wx), bus.y)
                r = 6
                self.canvas.create_oval(tap_sx - r, tap_sy - r,
                                        tap_sx + r, tap_sy + r,
                                        fill="#0066CC", outline="")

    def _finish_connection(self, wx: float, wy: float, to_bus_id: Optional[str]) -> None:
        kind = "tline" if self._tool == TOOL_TLINE else "feeder"
        if self._conn_from_bus not in self._buses:
            self._conn_from_bus = None
            return
        cid = f"{kind.upper()}-{len(self._connections) + 1}"
        if kind == "feeder":
            conn = DiagramConnection(cid, cid, kind, self._conn_from_bus, self._conn_from_x,
                                     to_point=(wx, wy))
        elif to_bus_id and to_bus_id != self._conn_from_bus:
            conn = DiagramConnection(cid, cid, kind, self._conn_from_bus, self._conn_from_x,
                                     to_bus=to_bus_id, to_x=wx)
        else:
            if self._on_status:
                msg = ("Same bus — click a different bus." if to_bus_id
                       else "No bus found there — click directly on a bus bar.")
                self._on_status(f"From '{self._buses[self._conn_from_bus].name}' — {msg}")
            return
        self._connections[cid] = conn
        self._set_selection("conn", cid)
        self._conn_from_bus = None
        self.redraw()

    def _delete_bus(self, bus_id: str) -> None:
        self._buses.pop(bus_id, None)
        for cid in [k for k, c in self._connections.items()
                    if c.from_bus == bus_id or c.to_bus == bus_id]:
            self._delete_connection(cid)
        for vid in [k for k, v in self._vts.items() if v.bus_id == bus_id]:
            self._vts.pop(vid)
        # Detach elements that referenced this bus.
        for xfmr in self._transformers.values():
            if xfmr.hv_bus == bus_id:
                xfmr.hv_bus = None
            if xfmr.lv_bus == bus_id:
                xfmr.lv_bus = None
        for src in self._sources.values():
            if src.bus == bus_id:
                src.bus = None
        for ld in self._loads.values():
            if ld.bus == bus_id:
                ld.bus = None
        self._set_selection(None, None)
        self.redraw()

    def _delete_connection(self, conn_id: str) -> None:
        self._connections.pop(conn_id, None)
        for cid in [k for k, c in self._cts.items() if c.connection_id == conn_id]:
            self._cts.pop(cid)
        self._set_selection(None, None)
        self.redraw()

    # ── Pan / zoom ────────────────────────────────────────────────────────

    def _pan_start(self, event: tk.Event) -> None:
        self._pan_start_pt = (event.x, event.y)

    def _pan_drag(self, event: tk.Event) -> None:
        if self._pan_start_pt:
            self._offset_x += event.x - self._pan_start_pt[0]
            self._offset_y += event.y - self._pan_start_pt[1]
            self._pan_start_pt = (event.x, event.y)
            self.redraw()

    def _pan_end(self, _event: tk.Event) -> None:
        self._pan_start_pt = None

    def _scroll(self, event: tk.Event) -> None:
        factor = 1.1 if (event.num == 4 or event.delta > 0) else 1 / 1.1
        cx, cy = event.x, event.y
        self._offset_x = cx - (cx - self._offset_x) * factor
        self._offset_y = cy - (cy - self._offset_y) * factor
        self._scale    = max(0.2, min(self._scale * factor, 8.0))
        self.redraw()

    # ── Selection ─────────────────────────────────────────────────────────

    def _set_selection(self, kind: Optional[str], elem_id: Optional[str]) -> None:
        self._selection = (kind, elem_id) if kind else None
        if self._on_select:
            self._on_select(self._selection)
        self.redraw()


def _point_to_segment_dist(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)))
    return math.hypot(px - x1 - t*dx, py - y1 - t*dy)
