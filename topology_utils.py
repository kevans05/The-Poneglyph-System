"""
topology_utils.py — Pure topology mutation helpers.

apply_reconfiguration() is the single entry point for all structural changes
to the in-memory topology dict.  It is called from api.py after the HTTP
request is validated and from sim_engine when mutations arrive while the
simulation is running.

All mutations operate on the raw topology dict (lists of device dicts) rather
than instantiated model objects, so they are fast and require no re-import.

Supported actions
-----------------
update_device         — patch arbitrary params on a device dict
update_position       — move device's (gx, gy) canvas coordinates
update_rotation       — rotate device symbol (0 / 90 / 180 / 270°)
delete_device         — remove device and scrub all references to it
add_device            — append a new device dict; optionally wire it up
rename_device         — change device ID everywhere (dict + all connection lists)
record_measurement    — save analog readings to the site DB (no topology change)
add_connection        — add primary bushing connection
add_secondary_connection — add analog (CT/VT secondary) connection
add_dc_connection     — add DC control wire with from/to terminal labels
delete_connection     — remove any connection type by target ID
"""

import site_db as _sdb

def apply_reconfiguration(data, req, active_site=None, active_session_id=None):
    target_id = req.get("id")
    action = req.get("action")

    if action == "update_device":
        for d in data["devices"]:
            if d["id"] == target_id:
                props = req.get("properties", {})
                for k, v in props.items():
                    if v is None:
                        d.pop(k, None)
                    else:
                        d[k] = v
                break
    elif action == "update_position":
        for d in data["devices"]:
            if d["id"] == target_id:
                d["gx"] = req.get("gx")
                d["gy"] = req.get("gy")
                break
    elif action == "update_rotation":
        for d in data["devices"]:
            if d["id"] == target_id:
                d["rotation"] = req.get("rotation", 0)
                break
    elif action == "delete_device":
        data["devices"] = [
            d for d in data["devices"] if d["id"] != target_id
        ]
        for d in data["devices"]:
            if "connections" in d:
                d["connections"] = [
                    c
                    for c in d["connections"]
                    if (c if isinstance(c, str) else c["id"]) != target_id
                ]
            if "secondary_connections" in d:
                d["secondary_connections"] = [
                    c for c in d["secondary_connections"] if c != target_id
                ]
            if "secondary2_connections" in d:
                d["secondary2_connections"] = [
                    c for c in d["secondary2_connections"] if c != target_id
                ]
            if "dc_connections" in d:
                d["dc_connections"] = [
                    c for c in d["dc_connections"] if (c if isinstance(c, str) else c["id"]) != target_id
                ]
            if "trip_connections" in d:
                d["trip_connections"] = [
                    c for c in d["trip_connections"] if c != target_id
                ]
            if "close_connections" in d:
                d["close_connections"] = [
                    c for c in d["close_connections"] if c != target_id
                ]
    elif action == "add_device":
        new_dev = req.get("device")
        if "gx" in req:
            new_dev["gx"] = req["gx"]
        if "gy" in req:
            new_dev["gy"] = req["gy"]
        data["devices"].append(new_dev)
        if "connect_to" in req:
            source_id = req["connect_to"]["id"]
            bushing = req["connect_to"]["bushing"]
            for d in data["devices"]:
                if d["id"] == source_id:
                    if "connections" not in d:
                        d["connections"] = []
                    conn = new_dev["id"]
                    if bushing:
                        conn = {"id": new_dev["id"], "via_bushing": bushing}
                    d["connections"].append(conn)
                    break
    elif action == "rename_device":
        old_id = target_id
        new_id = req.get("new_id", "").strip()
        if new_id and new_id != old_id:
            for d in data["devices"]:
                if d["id"] == old_id:
                    d["id"] = new_id
                for list_key in ["connections", "secondary_connections", "secondary2_connections", "dc_connections", "trip_connections", "close_connections"]:
                    if list_key in d:
                        d[list_key] = [
                            (new_id if c == old_id else c)
                            if isinstance(c, str)
                            else (
                                {**c, "id": new_id} if c["id"] == old_id else c
                            )
                            for c in d[list_key]
                        ]
                if d.get("location") == old_id:
                    d["location"] = new_id
            if data.get("reference", {}).get("device_id") == old_id:
                data["reference"]["device_id"] = new_id
    elif action == "record_measurement":
        meas = req.get("measurements", {})
        if active_site:
            _sdb.record_measurements(
                active_site,
                session_id=active_session_id,
                device_id=target_id,
                measurements=meas,
            )
    elif action == "add_connection":
        source_id = req.get("id")
        target_id = req.get("target_id")
        bushing = req.get("bushing")
        for d in data["devices"]:
            if d["id"] == source_id:
                if "connections" not in d:
                    d["connections"] = []
                new_conn = target_id
                if bushing:
                    new_conn = {"id": target_id, "via_bushing": bushing}
                d["connections"].append(new_conn)
                break
    elif action == "add_secondary_connection":
        source_id = req.get("id")
        target_id = req.get("target_id")
        for d in data["devices"]:
            if d["id"] == source_id:
                if "secondary_connections" not in d:
                    d["secondary_connections"] = []
                if target_id not in d["secondary_connections"]:
                    d["secondary_connections"].append(target_id)
                break
    elif action == "add_secondary2_connection":
        source_id = req.get("id")
        target_id = req.get("target_id")
        for d in data["devices"]:
            if d["id"] == source_id:
                if "secondary2_connections" not in d:
                    d["secondary2_connections"] = []
                if target_id not in d["secondary2_connections"]:
                    d["secondary2_connections"].append(target_id)
                break
    elif action == "add_dc_connection":
        source_id = req.get("id")
        target_id = req.get("target_id")
        from_label = req.get("from")
        to_label = req.get("to")
        for d in data["devices"]:
            if d["id"] == source_id:
                if "dc_connections" not in d:
                    d["dc_connections"] = []
                new_conn = {"id": target_id, "from": from_label, "to": to_label}
                d["dc_connections"].append(new_conn)
                break
    elif action == "delete_connection":
        source_id = req.get("id")
        target_id = req.get("target_id")
        for d in data["devices"]:
            if d["id"] == source_id:
                for list_key in ["connections", "secondary_connections", "secondary2_connections", "dc_connections", "trip_connections", "close_connections"]:
                    if list_key in d:
                        d[list_key] = [
                            c for c in d[list_key] 
                            if (c if isinstance(c, str) else c.get("id")) != target_id
                        ]
                break
    return data
