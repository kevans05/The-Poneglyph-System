"""
topo_merge.py — structural 3-way merge for substation topology.

A substation version is the full topology dict:
    { "devices": [ {id, type, status, ...params, connections?, secondary_connections?} ],
      "wire_bends": {...}, "project_info": {...}, "reference": {...} }

The merge is keyed by device id and, within a device, by field — a line-diff
would invent conflicts across re-ordered JSON.  Connection lists are merged as
sets keyed by the neighbour id so "I added CT-A, you added CT-B" both land.

Contract
--------
merge(base, ours, theirs) -> (merged, conflicts)
    `merged` already contains every non-conflicting change from both sides.
    Each conflict is provisionally resolved to *ours*; `conflicts` lists what
    still needs a human call.

resolve(merged, conflicts) -> merged
    Apply each conflict's `choice` ("ours" | "theirs" | {"value": ...}).

content_hash(topology) -> hex str
    Deterministic id for a version (ignores dict/list ordering of devices).
"""

import copy
import hashlib
import json

# Fields that never conflict — cosmetic placement. Ours wins silently.
_NONCONFLICT_FIELDS = {"gx", "gy", "x", "y", "bend_frac"}

# List-valued fields merged element-wise by neighbour key rather than as opaque
# values. Value = the dict key holding the neighbour id, or None for a bare
# list[str].
_CONN_FIELDS = {"connections": "id", "secondary_connections": None}


# ── hashing ──────────────────────────────────────────────────────────────────

def _canonical(topology: dict) -> str:
    devices = sorted(topology.get("devices", []), key=lambda d: str(d.get("id", "")))
    shell = {k: v for k, v in topology.items() if k != "devices"}
    return json.dumps(
        {"shell": shell, "devices": devices},
        sort_keys=True, separators=(",", ":"), default=str,
    )


def content_hash(topology: dict, parent_id: str = "", branch: str = "main") -> str:
    h = hashlib.sha256()
    h.update(_canonical(topology).encode("utf-8"))
    h.update(b"\x00")
    h.update(parent_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(branch.encode("utf-8"))
    return h.hexdigest()


def topo_equal(a: dict, b: dict) -> bool:
    return _canonical(a) == _canonical(b)


# ── merge ────────────────────────────────────────────────────────────────────

def _dev_map(topo: dict) -> dict:
    return {str(d["id"]): d for d in (topo or {}).get("devices", []) if "id" in d}


def _conn_key_fn(field: str):
    key = _CONN_FIELDS[field]
    if key is None:
        return lambda c: str(c)
    return lambda c: str(c.get(key)) if isinstance(c, dict) else str(c)


def _merge_conn_list(device_id, field, base_l, our_l, their_l):
    kf = _conn_key_fn(field)
    bm = {kf(c): c for c in (base_l or [])}
    om = {kf(c): c for c in (our_l or [])}
    tm = {kf(c): c for c in (their_l or [])}
    out, conflicts = [], []
    # Preserve ours' order, then any their-only entries.
    order = list(om.keys()) + [k for k in tm if k not in om]
    for k in order:
        bc, oc, tc = bm.get(k), om.get(k), tm.get(k)
        if oc == tc:
            v = oc
        elif oc == bc:
            v = tc          # only theirs touched this neighbour (maybe removed)
        elif tc == bc:
            v = oc          # only ours touched it
        else:
            conflicts.append({
                "kind": "connection", "device_id": device_id, "field": field,
                "target": k, "base": bc, "ours": oc, "theirs": tc,
            })
            v = oc          # provisional
        if v is not None:
            out.append(v)
    return out, conflicts


def _merge_device(device_id, bd, od, td):
    out, conflicts = {}, []
    keys = list(dict.fromkeys(list(od.keys()) + list(td.keys()) + list((bd or {}).keys())))
    for k in keys:
        if k in _CONN_FIELDS:
            merged, cc = _merge_conn_list(
                device_id, k,
                (bd or {}).get(k), od.get(k), td.get(k),
            )
            out[k] = merged
            conflicts += cc
            continue
        bv = (bd or {}).get(k)
        ov = od.get(k)
        tv = td.get(k)
        if k in _NONCONFLICT_FIELDS:
            out[k] = ov if ov is not None else tv
            continue
        if ov == tv or ov == bv and tv == bv:
            out[k] = ov if ov is not None else tv
        elif ov == bv:
            if tv is not None:
                out[k] = tv          # only theirs changed
        elif tv == bv:
            out[k] = ov              # only ours changed
        else:
            conflicts.append({
                "kind": "field", "device_id": device_id, "field": k,
                "base": bv, "ours": ov, "theirs": tv,
            })
            out[k] = ov              # provisional
    return out, conflicts


def merge(base: dict, ours: dict, theirs: dict):
    b, o, t = _dev_map(base), _dev_map(ours), _dev_map(theirs)
    ids = list(dict.fromkeys(list(o.keys()) + list(t.keys()) + list(b.keys())))

    merged = copy.deepcopy(ours)
    result_devices, conflicts = [], []

    for did in ids:
        bd, od, td = b.get(did), o.get(did), t.get(did)
        if od == td:
            pick = od
        elif od == bd:
            pick = td                         # only theirs changed (incl. delete)
        elif td == bd:
            pick = od                         # only ours changed (incl. delete)
        elif od is None or td is None:
            conflicts.append({
                "kind": "delete-edit", "device_id": did,
                "base": bd, "ours": od, "theirs": td,
            })
            pick = od if od is not None else td   # provisional: keep the surviving edit
        else:
            pick, dcs = _merge_device(did, bd, od, td)
            conflicts += dcs
        if pick is not None:
            result_devices.append(pick)

    merged["devices"] = result_devices
    merged["wire_bends"] = {
        **(theirs.get("wire_bends") or {}),
        **(ours.get("wire_bends") or {}),
    }
    return merged, conflicts


# ── resolution ───────────────────────────────────────────────────────────────

def resolve(merged: dict, conflicts: list) -> dict:
    """Apply a `choice` on each conflict. `choice` is 'ours' (no-op — already
    applied), 'theirs', or {'value': <x>}."""
    out = copy.deepcopy(merged)
    devs = {str(d["id"]): d for d in out.get("devices", []) if "id" in d}

    for c in conflicts or []:
        choice = c.get("choice", "ours")
        if choice == "ours":
            continue
        did = c.get("device_id")
        kind = c.get("kind")

        if kind == "delete-edit":
            if choice == "theirs":
                if c.get("theirs") is None:
                    out["devices"] = [d for d in out["devices"] if str(d.get("id")) != did]
                    devs.pop(did, None)
                else:
                    _upsert_device(out, devs, c["theirs"])
            elif isinstance(choice, dict):
                _upsert_device(out, devs, choice["value"])
            continue

        dev = devs.get(did)
        if dev is None:
            continue

        if kind == "field":
            field = c["field"]
            if choice == "theirs":
                if c.get("theirs") is None:
                    dev.pop(field, None)
                else:
                    dev[field] = c["theirs"]
            elif isinstance(choice, dict):
                dev[field] = choice["value"]

        elif kind == "connection":
            field = c["field"]
            target = str(c["target"])
            lst = dev.setdefault(field, [])
            new_val = c["theirs"] if choice == "theirs" else (
                choice["value"] if isinstance(choice, dict) else None
            )
            kf = _conn_key_fn(field)
            lst[:] = [x for x in lst if kf(x) != target]
            if new_val is not None:
                lst.append(new_val)

    return out


def _upsert_device(out, devs, dev_obj):
    did = str(dev_obj.get("id"))
    if did in devs:
        devs[did].clear()
        devs[did].update(dev_obj)
    else:
        out["devices"].append(dev_obj)
        devs[did] = dev_obj
