"""
test_audit.py — turns raw recorded measurements into review-ready phasor sets,
neutral/residual checks, and primary→secondary chain comparisons for the
Tests → AUDIT view.

Pure functions on plain dicts; no DB or HTTP here. Input is the shape returned
by site_db.get_test_report_data() plus the active topology's device list.

Measurement keys are free-form strings grown organically by the measurement
wizard ("Phase A Current", "Sec Voltage Phase A", "Phase A-B Voltage",
"Neutral Current", ...) — parse_measurement_key() is deliberately tolerant of
that rather than assuming one canonical format.
"""

import math
import re

_PHASES = ("A", "B", "C")


def parse_measurement_key(key: str):
    """'Phase A Current' -> ('A', 'current'). Returns None if unrecognised."""
    k = (key or "").strip()
    if not k:
        return None
    low = k.lower()
    if low.startswith("neutral"):
        phase = "N"
    else:
        m = re.search(r"\bphase\s+([abc](?:-?[abc])?)\b", k, re.I)
        if not m:
            return None
        phase = m.group(1).upper().replace("-", "")
        if phase not in ("A", "B", "C", "AB", "BC", "CA"):
            return None
    if "i-angle" in low:
        qty = "i-angle"
    elif "v-angle" in low:
        qty = "v-angle"
    elif "current" in low:
        qty = "current"
    elif "voltage" in low:
        qty = "voltage"
    else:
        return None
    return phase, qty


def _phasor_families(raw: dict) -> dict:
    """{'Phase A Current': 120.0, 'Phase A I-Angle': -30.0, ...}
    -> {'current': {'A': {'mag':120.0,'ang':-30.0}}, 'voltage': {...}}"""
    fam = {"current": {}, "voltage": {}}
    for key, value in raw.items():
        parsed = parse_measurement_key(key)
        if not parsed or value is None:
            continue
        phase, qty = parsed
        family = "current" if qty in ("current", "i-angle") else "voltage"
        slot = fam[family].setdefault(phase, {})
        if qty in ("current", "voltage"):
            slot["mag"] = value
        else:
            slot["ang"] = value
    for family in fam:
        fam[family] = {p: v for p, v in fam[family].items() if "mag" in v}
    return fam


def _vector_sum(components):
    """[(mag, ang_deg), ...] -> (mag, ang_deg) of the phasor sum."""
    re_sum = im_sum = 0.0
    for mag, ang in components:
        rad = math.radians(ang)
        re_sum += mag * math.cos(rad)
        im_sum += mag * math.sin(rad)
    mag = math.hypot(re_sum, im_sum)
    ang = math.degrees(math.atan2(im_sum, re_sum)) if mag > 1e-12 else 0.0
    return mag, ang


def compute_residual(fam: dict):
    """fam: {'A':{'mag','ang'}, 'B':..., 'C':..., 'N':...(optional)}.
    None unless A/B/C are all present with both mag and angle."""
    if not all(p in fam and "mag" in fam[p] and "ang" in fam[p] for p in _PHASES):
        return None
    comps = [(fam[p]["mag"], fam[p]["ang"]) for p in _PHASES]
    avg_mag = sum(c[0] for c in comps) / 3.0
    computed_mag, computed_ang = _vector_sum(comps)
    out = {
        "avg_phase_mag": avg_mag,
        "computed_mag": computed_mag,
        "computed_ang": computed_ang,
        "computed_pct": (computed_mag / avg_mag * 100.0) if avg_mag > 1e-9 else None,
    }
    n = fam.get("N")
    if n and "mag" in n:
        out["measured_mag"] = n["mag"]
        out["measured_ang"] = n.get("ang")
        out["measured_pct"] = (n["mag"] / avg_mag * 100.0) if avg_mag > 1e-9 else None
        if "ang" in n:
            out["diff_pct"] = (
                abs(n["mag"] - computed_mag) / avg_mag * 100.0 if avg_mag > 1e-9 else None
            )
    return out


def _build_secondary_edges(devices: list) -> dict:
    """{downstream_id: [(upstream_id, sign), ...]}, mirroring the live sign
    logic in phasors/devices/protection.py (ProtectionDevice.current):
    input_polarities overrides; DIFFERENTIAL mode defaults every input past
    the first to -1 unless explicitly overridden."""
    by_id = {d["id"]: d for d in devices}
    inputs: dict = {}
    for d in devices:
        for target in d.get("secondary_connections") or []:
            inputs.setdefault(target, []).append(d["id"])

    edges = {}
    for downstream_id, upstream_ids in inputs.items():
        down = by_id.get(downstream_id, {})
        polarities = down.get("input_polarities") or {}
        mode = (down.get("mode") or "").upper()
        signed = []
        for i, uid in enumerate(upstream_ids):
            sign = polarities.get(uid, 1)
            if mode == "DIFFERENTIAL" and i > 0 and uid not in polarities:
                sign = -1
            signed.append((uid, sign))
        edges[downstream_id] = signed
    return edges


def build_audit(report_data: dict, devices: list) -> dict:
    """report_data: site_db.get_test_report_data() output.
    devices: the active topology's raw device list (for chain edges + types).
    """
    by_id_type = {d["id"]: d.get("type", "") for d in devices}
    edges = _build_secondary_edges(devices)

    device_rows: dict = {}
    for sess in report_data.get("sessions", []):
        sid = sess["id"]
        meta = {
            "epoch": sess.get("epoch"),
            "technician": sess.get("technician", ""),
            "instrument": sess.get("instrument", ""),
            "label": sess.get("label", ""),
        }
        for device_id, raw in (sess.get("by_device") or {}).items():
            flat_raw = {k: v["value"] for k, v in raw.items()}
            fam = _phasor_families(flat_raw)
            entry = device_rows.setdefault(
                device_id, {"type": by_id_type.get(device_id, ""), "sessions": {}}
            )
            entry["sessions"][sid] = {
                **meta,
                "raw": flat_raw,
                "phasors": fam,
                "residual": {
                    "current": compute_residual(fam["current"]),
                    "voltage": compute_residual(fam["voltage"]),
                },
            }

    # Chain expectations: for each device fed by others (CT -> CTTB -> Relay,
    # etc.), compare its recorded phase value against the polarity-weighted
    # vector sum of what its inputs recorded in the same session.
    chain_checks = []
    for downstream_id, signed_inputs in edges.items():
        down_entry = device_rows.get(downstream_id)
        if not down_entry:
            continue
        for sid, down_sess in down_entry["sessions"].items():
            for family in ("current", "voltage"):
                down_fam = down_sess["phasors"].get(family) or {}
                if not down_fam:
                    continue
                for phase in list(_PHASES) + ["N"]:
                    if phase not in down_fam or "mag" not in down_fam[phase]:
                        continue
                    comps, missing = [], []
                    for uid, sign in signed_inputs:
                        up_sess = (device_rows.get(uid) or {}).get("sessions", {}).get(sid)
                        up_val = ((up_sess or {}).get("phasors", {}).get(family) or {}).get(phase)
                        if up_val and "mag" in up_val and "ang" in up_val:
                            mag = sign * up_val["mag"]
                            ang = up_val["ang"] + (180.0 if mag < 0 else 0.0)
                            comps.append((abs(mag), ang))
                        else:
                            missing.append(uid)
                    if not comps:
                        continue
                    exp_mag, exp_ang = _vector_sum(comps)
                    act = down_fam[phase]
                    # Normalise against the operating magnitude (avg of the inputs
                    # that fed this comparison), not the expected value itself —
                    # a differential/restraint check legitimately expects ~0, and
                    # dividing by that would blow up a perfectly good match.
                    avg_operand_mag = sum(c[0] for c in comps) / len(comps)
                    mag_diff_pct = (
                        abs(act["mag"] - exp_mag) / avg_operand_mag * 100.0
                        if avg_operand_mag > 1e-9 else None
                    )
                    ang_diff = None
                    if "ang" in act and exp_mag > 1e-9:
                        d = (act["ang"] - exp_ang + 180) % 360 - 180
                        ang_diff = abs(d)
                    chain_checks.append({
                        "downstream_id": downstream_id,
                        "downstream_type": by_id_type.get(downstream_id, ""),
                        "upstream_ids": [u for u, _ in signed_inputs],
                        "missing_upstream": missing,
                        "session_id": sid,
                        "family": family,
                        "phase": phase,
                        "expected_mag": exp_mag,
                        "expected_ang": exp_ang,
                        "actual_mag": act["mag"],
                        "actual_ang": act.get("ang"),
                        "mag_diff_pct": mag_diff_pct,
                        "ang_diff_deg": ang_diff,
                    })

    return {"devices": device_rows, "chain_checks": chain_checks}
