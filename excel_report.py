"""Build a load-test Excel report from a test's stored data.

Loads templates/load_test_template.xlsx, fills cell values per the field map
agreed with the user, and returns the workbook as bytes.

Field map (Load Test sheet):
    J4:Z4    -> tests.name (load test name)
    AM4:AS4  -> site_info.station
    AX4:BD4  -> tests.epoch -> YYYY-MM-DD
    J5:Z5    -> blank
    AM5:BD5  -> tests.created_by
    A8       -> multi-line list of equipment + drawings + initial conditions
    J17:AB17 -> system reference VT name (blank in v1)
    AL17:AR17-> system reference VT magnitude (blank in v1)
    AU17:BD17-> system reference VT angle (blank in v1)

Per CT/VT/RLY block (5 in template, dynamically inserted/removed below):
    block_first_row = 20, 26, 32, 38, 44, ... (stride 6)
    A{r}     -> device type
    G{r}:T{r}-> device name
    G{r+1}   -> root device (parent + bushing, e.g. "2CB2 X")
    C{r+2}   -> S&I (phases shorted/isolated)
    L{r+2}   -> ratio text (e.g. "600:5")
    J{r+3}   -> equipment status

For each phase (A, B, C, N):
    {col}{r}   -> phase label ("A" / "A to N" / "A to B" depending on type)
    {col}{r+1} -> measured magnitude
    {col2}{r+1}-> measured angle
    {col}{r+2} -> calculated magnitude (= measured * ratio_factor)
    {col2}{r+2}-> calculated angle (= measured)
"""

from __future__ import annotations

import io
import os
from copy import copy
from datetime import datetime, timezone

import openpyxl
from openpyxl.utils import get_column_letter

import site_db


_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "templates", "load_test_template.xlsx"
)

_BLOCK_STRIDE = 6           # rows per block (4 content + 2 spacer)
_FIRST_BLOCK_ROW = 20       # first content row of block 1
_TEMPLATE_BLOCK_COUNT = 5   # blocks already laid out in the template
_REMARKS_ROW_TEMPLATE = 51  # remarks header in the unmodified template

# Per-phase column anchors (top-left of each merged region) keyed by phase.
# Row offsets relative to the block's first row r:
#   r+0: phase label cell (wide) -- merged from these columns to the right
#   r+1: measured mag / angle cells
#   r+2: calculated mag / angle cells
_PHASE_COLS = {
    # phase: (label_col, mag_col, ang_col)
    "A": ("U",  "U",  "Y"),
    "B": ("AD", "AD", "AH"),
    "C": ("AM", "AM", "AQ"),
    "N": ("AV", "AV", "AZ"),
}

# Measurement keys we expect in the DB for each phase.
# Maps phase -> (mag_key, angle_key). Voltage devices fall back to V- variants.
_CURRENT_KEYS = {
    "A": ("Phase A Current", "Phase A I-Angle"),
    "B": ("Phase B Current", "Phase B I-Angle"),
    "C": ("Phase C Current", "Phase C I-Angle"),
    "N": ("Neutral Current", "Neutral I-Angle"),
}
_VOLTAGE_KEYS = {
    "A": ("Phase A Voltage", "Phase A V-Angle"),
    "B": ("Phase B Voltage", "Phase B V-Angle"),
    "C": ("Phase C Voltage", "Phase C V-Angle"),
    "N": ("Neutral Voltage",  "Neutral V-Angle"),
}


# ── public entry point ────────────────────────────────────────────────────────

def build_load_test_report(db_path: str, test_id: str) -> bytes | None:
    """Return the populated .xlsx as bytes, or None if the test doesn't exist."""
    data = site_db.get_test_report_data(db_path, test_id)
    if not data:
        return None

    topology = site_db.get_latest_topology(db_path) or {}
    topo_devices = {d.get("id"): d for d in topology.get("devices", [])}

    wb = openpyxl.load_workbook(_TEMPLATE_PATH)
    # Drop the alternate "Template" sheet so the deliverable is one tab.
    if "Template" in wb.sheetnames:
        del wb["Template"]
    ws = wb["Load Test"]

    _fill_header(ws, data)
    _fill_equipment_block(ws, data)

    devices = _devices_for_test(data, topo_devices)
    _ensure_block_count(ws, len(devices))
    for i, dev in enumerate(devices):
        _fill_block(ws, _FIRST_BLOCK_ROW + i * _BLOCK_STRIDE, dev, data)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── header / equipment ────────────────────────────────────────────────────────

def _fill_header(ws, data: dict) -> None:
    test = data.get("test", {}) or {}
    site = data.get("site", {}) or {}

    ws["J4"]  = test.get("name", "")
    ws["AM4"] = site.get("station", "")
    epoch = test.get("epoch")
    if epoch:
        ws["AX4"] = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")
    # J5 stays blank per the field map.
    ws["AM5"] = test.get("created_by", "")


def _fill_equipment_block(ws, data: dict) -> None:
    """Populate the multi-line A8 region with equipment list, drawings, and notes."""
    devices = sorted({
        did
        for sess in data.get("sessions", [])
        for did in (sess.get("by_device") or {}).keys()
    })
    drawings = data.get("drawings", []) or []

    parts: list[str] = []

    parts.append("Equipment:")
    if devices:
        parts.extend(f"  - {did}" for did in devices)
    else:
        parts.append("  (none)")

    parts.append("")
    parts.append("Drawings:")
    if drawings:
        for d in drawings:
            title = (d.get("title") or "").strip() or "(untitled)"
            url = (d.get("url") or "").strip()
            rev = (d.get("revision") or "").strip()
            line = f"  - {title}"
            if rev:
                line += f" [rev {rev}]"
            if url:
                line += f"  {url}"
            parts.append(line)
    else:
        parts.append("  (none)")

    initial = (data.get("test", {}) or {}).get("description", "")
    parts.append("")
    parts.append("Initial Conditions:")
    parts.append(initial.strip() if initial else "")

    ws["A8"] = "\n".join(parts)


# ── device selection ──────────────────────────────────────────────────────────

def _devices_for_test(data: dict, topo_devices: dict) -> list[dict]:
    """Return ordered list of dicts: {id, type, name, location, ratio, ratio_factor, root_device, kind}."""
    seen = set()
    ordered: list[str] = []
    for sess in sorted(data.get("sessions", []), key=lambda s: s.get("epoch", 0)):
        for did in (sess.get("by_device") or {}).keys():
            if did not in seen:
                seen.add(did)
                ordered.append(did)

    devs: list[dict] = []
    for did in ordered:
        topo = topo_devices.get(did, {}) or {}
        ratio_text = (topo.get("ratio") or "").strip()
        ratio_factor = _ratio_to_factor(ratio_text) if ratio_text else None
        bushing = (topo.get("bushing") or "").strip()
        parent = _root_device_for(did, topo, topo_devices)
        root_device = f"{parent} {bushing}".strip() if parent or bushing else ""

        dtype = topo.get("type") or _infer_type_from_measurements(data, did)
        devs.append({
            "id": did,
            "type": dtype,
            "name": did,
            "location": (topo.get("location") or "").strip(),
            "ratio": ratio_text,
            "ratio_factor": ratio_factor,
            "root_device": root_device,
            "kind": _kind_for_type(dtype),
        })
    return devs


def _ratio_to_factor(ratio_text: str) -> float | None:
    """'600:5' -> 120.0; returns None on parse failure."""
    try:
        a, b = ratio_text.split(":", 1)
        return float(a) / float(b)
    except (ValueError, ZeroDivisionError):
        return None


def _root_device_for(did: str, topo: dict, topo_devices: dict) -> str:
    """Best-effort guess at the parent device (e.g. CB) the CT/VT lives on."""
    for key in ("parent", "host", "host_device", "downstream_device"):
        v = topo.get(key)
        if v:
            return str(v)
    # Fall back: scan devices for one referencing this CT/VT.
    for other_id, other in topo_devices.items():
        for key in ("ct_ids", "vt_ids", "secondary_devices", "x_secondaries", "h_secondaries"):
            ids = other.get(key)
            if isinstance(ids, list) and did in ids:
                return other_id
    return ""


def _infer_type_from_measurements(data: dict, did: str) -> str:
    """Look at the measurement keys for this device to guess CT vs VT vs other."""
    keys: set[str] = set()
    for sess in data.get("sessions", []):
        kvs = (sess.get("by_device") or {}).get(did) or {}
        keys.update(kvs.keys())
    if any("Voltage" in k or "V-Angle" in k for k in keys):
        return "VoltageTransformer"
    if any("Current" in k or "I-Angle" in k for k in keys):
        return "CurrentTransformer"
    return ""


def _kind_for_type(dtype: str) -> str:
    """'current' if the device produces current measurements, 'voltage' if voltage."""
    t = (dtype or "").lower()
    if "voltagetransformer" in t or "vt" == t or "dualwindingvt" in t:
        return "voltage"
    return "current"


# ── per-block fill ────────────────────────────────────────────────────────────

def _fill_block(ws, r: int, dev: dict, data: dict) -> None:
    ws.cell(row=r,     column=1).value = _short_type(dev["type"])    # A: device type
    ws[f"G{r}"]   = dev["name"]
    ws[f"G{r+1}"] = dev["root_device"]
    ws[f"C{r+2}"] = ""                                                # S&I: blank in v1
    ws[f"L{r+2}"] = dev["ratio"]
    ws[f"J{r+3}"] = ""                                                # equipment status: blank

    keys = _VOLTAGE_KEYS if dev["kind"] == "voltage" else _CURRENT_KEYS
    measurements = _latest_measurements_for_device(data, dev["id"])
    ratio = dev["ratio_factor"]

    for phase, (label_col, mag_col, ang_col) in _PHASE_COLS.items():
        mag_key, ang_key = keys[phase]
        mag = measurements.get(mag_key, {}).get("value")
        ang = measurements.get(ang_key, {}).get("value")

        ws[f"{label_col}{r}"] = _phase_label(phase, dev["kind"])
        if mag is not None:
            ws[f"{mag_col}{r+1}"] = mag
        if ang is not None:
            ws[f"{ang_col}{r+1}"] = ang
        if mag is not None and ratio:
            ws[f"{mag_col}{r+2}"] = mag * ratio
        if ang is not None:
            ws[f"{ang_col}{r+2}"] = ang


def _short_type(dtype: str) -> str:
    """Map class names to the short labels used on a load-test form."""
    t = (dtype or "").lower()
    if "currenttransformer" in t: return "CT"
    if "voltagetransformer" in t or "dualwindingvt" in t: return "VT"
    if "relay" in t: return "RLY"
    if "cttb" in t: return "CTTB"
    return dtype or ""


def _phase_label(phase: str, kind: str) -> str:
    if kind == "voltage":
        return "" if phase == "N" else f"{phase} to N"
    return phase


def _latest_measurements_for_device(data: dict, device_id: str) -> dict:
    """Return {key: {value, epoch}} keeping the newest epoch per key."""
    result: dict[str, dict] = {}
    for sess in data.get("sessions", []):
        kvs = (sess.get("by_device") or {}).get(device_id) or {}
        for key, mv in kvs.items():
            existing = result.get(key)
            if existing is None or (mv.get("epoch") or 0) > (existing.get("epoch") or 0):
                result[key] = mv
    return result


# ── dynamic block count (insert / delete) ─────────────────────────────────────

def _ensure_block_count(ws, n: int) -> None:
    """Add or remove CT/VT/RLY blocks so the sheet has exactly max(n, 1) of them."""
    n = max(n, 1)
    if n == _TEMPLATE_BLOCK_COUNT:
        return
    if n < _TEMPLATE_BLOCK_COUNT:
        first_to_drop = _FIRST_BLOCK_ROW + n * _BLOCK_STRIDE
        amount = _BLOCK_STRIDE * (_TEMPLATE_BLOCK_COUNT - n)
        _delete_rows_with_merges(ws, first_to_drop, amount)
        return

    extra = n - _TEMPLATE_BLOCK_COUNT
    src_first = _FIRST_BLOCK_ROW + (_TEMPLATE_BLOCK_COUNT - 1) * _BLOCK_STRIDE  # block 5
    insert_at = src_first + _BLOCK_STRIDE  # row immediately after block 5's spacer

    # Snapshot the source block before insertion (so coordinates don't shift).
    src_cells = [
        [_snapshot_cell(ws.cell(row=src_first + dr, column=col))
         for col in range(1, ws.max_column + 1)]
        for dr in range(_BLOCK_STRIDE)
    ]
    src_heights = [ws.row_dimensions[src_first + dr].height for dr in range(_BLOCK_STRIDE)]
    src_merges = [
        (rng.min_row - src_first, rng.max_row - src_first, rng.min_col, rng.max_col)
        for rng in list(ws.merged_cells.ranges)
        if src_first <= rng.min_row and rng.max_row < src_first + _BLOCK_STRIDE
    ]

    _insert_rows_with_merges(ws, insert_at, _BLOCK_STRIDE * extra)

    for blk in range(extra):
        dst_first = insert_at + blk * _BLOCK_STRIDE
        for dr in range(_BLOCK_STRIDE):
            for ci, snap in enumerate(src_cells[dr], start=1):
                _restore_cell(ws.cell(row=dst_first + dr, column=ci), snap)
            if src_heights[dr] is not None:
                ws.row_dimensions[dst_first + dr].height = src_heights[dr]
        for r0, r1, c0, c1 in src_merges:
            ws.merge_cells(
                start_row=dst_first + r0, end_row=dst_first + r1,
                start_column=c0, end_column=c1,
            )


def _insert_rows_with_merges(ws, idx: int, amount: int) -> None:
    """openpyxl insert_rows shifts cell values and styles, but not merged ranges.

    Re-bind every merge whose start row is >= idx so it lands in the right place
    after the insertion. Merges entirely above idx are untouched.
    """
    affected = [rng for rng in list(ws.merged_cells.ranges) if rng.min_row >= idx]
    for rng in affected:
        ws.unmerge_cells(str(rng))
    ws.insert_rows(idx, amount)
    for rng in affected:
        ws.merge_cells(
            start_row=rng.min_row + amount, end_row=rng.max_row + amount,
            start_column=rng.min_col, end_column=rng.max_col,
        )


def _delete_rows_with_merges(ws, idx: int, amount: int) -> None:
    """Delete rows and update merged-cell ranges to match.

    Merges fully inside the deleted region are dropped. Merges starting after
    the region shift up by `amount`. Merges that span the region get their
    end row clamped to (idx - 1), which is the simplest correct behaviour for
    our layout (block-internal merges never span the deleted region).
    """
    end = idx + amount  # first row that is *not* deleted
    for rng in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(rng))
        if rng.max_row < idx:
            new_min, new_max = rng.min_row, rng.max_row
        elif rng.min_row >= end:
            new_min, new_max = rng.min_row - amount, rng.max_row - amount
        elif rng.min_row < idx <= rng.max_row < end:
            new_min, new_max = rng.min_row, idx - 1
        elif idx <= rng.min_row and rng.max_row < end:
            continue  # entirely inside the deleted region; drop
        else:
            new_min = min(rng.min_row, idx)
            new_max = rng.max_row - amount
        if new_max < new_min:
            continue
        ws.merge_cells(
            start_row=new_min, end_row=new_max,
            start_column=rng.min_col, end_column=rng.max_col,
        )
    ws.delete_rows(idx, amount)


def _snapshot_cell(cell) -> dict:
    """Capture enough of a cell's state to recreate it after row insertion."""
    return {
        "value": cell.value,
        "font": copy(cell.font),
        "border": copy(cell.border),
        "fill": copy(cell.fill),
        "alignment": copy(cell.alignment),
        "number_format": cell.number_format,
        "protection": copy(cell.protection),
    }


def _restore_cell(cell, snap: dict) -> None:
    cell.value = snap["value"]
    cell.font = snap["font"]
    cell.border = snap["border"]
    cell.fill = snap["fill"]
    cell.alignment = snap["alignment"]
    cell.number_format = snap["number_format"]
    cell.protection = snap["protection"]
