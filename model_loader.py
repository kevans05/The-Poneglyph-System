"""
Shared logic for loading the substation model from topology JSON.
"""

from phasors.devices.factory import DeviceFactory
import logging

def _upstream_chain(dev):
    """Return the set of object ids reachable from dev (inclusive) via upstream_device links."""
    visited = set()
    cur = dev
    while cur is not None and id(cur) not in visited:
        visited.add(id(cur))
        cur = getattr(cur, "upstream_device", None)
    return visited

def load_substation_model(topology: dict):
    """Reconstruct the device graph and connections from topology JSON.
    Returns a dictionary of {device_id: DeviceInstance}.
    """
    if not topology:
        return {}

    devices = {}
    for d in topology.get("devices", []):
        dev = DeviceFactory.create_device(d)
        if dev:
            if "gx" in d: dev.gx = d["gx"]
            if "gy" in d: dev.gy = d["gy"]
            if "rotation" in d: dev.rotation = d["rotation"]
            devices[dev.name] = dev

    for d in topology.get("devices", []):
        did = d["id"]
        if did not in devices: continue
        
        # Primary connections
        for c in d.get("connections", []):
            tid = c if isinstance(c, str) else c["id"]
            b = None if isinstance(c, str) else c.get("via_bushing")
            if tid in devices:
                if b and b.upper() in ("H", "Y"):
                    # devices[tid].connect(devices[did]) → did.upstream_device = tid
                    # Cycle if did is already reachable from tid's upstream chain
                    if id(devices[did]) in _upstream_chain(devices[tid]):
                        logging.warning("Skipping connection %s→%s: would create an upstream_device cycle", tid, did)
                    else:
                        devices[tid].connect(devices[did])
                elif b:
                    # devices[did].connect(devices[tid], ...) → tid.upstream_device = did
                    # Cycle if tid is already reachable from did's upstream chain
                    if id(devices[tid]) in _upstream_chain(devices[did]):
                        logging.warning("Skipping connection %s→%s: would create an upstream_device cycle", did, tid)
                    else:
                        devices[did].connect(devices[tid], to_bushing=b)
                else:
                    # devices[did].connect(devices[tid]) → tid.upstream_device = did
                    # Cycle if tid is already reachable from did's upstream chain
                    if id(devices[tid]) in _upstream_chain(devices[did]):
                        logging.warning("Skipping connection %s→%s: would create an upstream_device cycle", did, tid)
                    else:
                        devices[did].connect(devices[tid])
        
        # Secondary connections
        for c in d.get("secondary_connections", []):
            if c in devices:
                if hasattr(devices[did], "connect_secondary"):
                    devices[did].connect_secondary(devices[c])
                else:
                    devices[did].connect(devices[c])

        # Winding-2 secondary connections (DualWindingVT only)
        for c in d.get("secondary2_connections", []):
            if c in devices:
                if hasattr(devices[did], "connect_secondary2"):
                    devices[did].connect_secondary2(devices[c])
                    
        # DC connections
        for c in d.get("dc_connections", []):
            tid = c if isinstance(c, str) else c.get("id")
            from_label = None if isinstance(c, str) else c.get("from")
            to_label = None if isinstance(c, str) else c.get("to")
            if tid in devices:
                if hasattr(devices[did], "connect_dc"):
                    devices[did].connect_dc(devices[tid], from_label=from_label, to_label=to_label)
                else:
                    devices[did].connect(devices[tid])
                    
        # Trip/Close
        for c in d.get("trip_connections", []):
            if c in devices:
                if hasattr(devices[did], "add_trip_dc"): devices[did].add_trip_dc(devices[c])
                elif hasattr(devices[c], "add_trip_dc"): devices[c].add_trip_dc(devices[did])
        for c in d.get("close_connections", []):
            if c in devices:
                if hasattr(devices[did], "add_close_dc"): devices[did].add_close_dc(devices[c])
                elif hasattr(devices[c], "add_close_dc"): devices[c].add_close_dc(devices[did])

    # Auto-configure hosts
    for did, dev in devices.items():
        if hasattr(dev, "location") and getattr(dev, "upstream_device", None) is None:
            host = devices.get(dev.location)
            if host:
                dev.upstream_device = host
                if hasattr(dev, "auto_configure"):
                    dev.auto_configure(host)

    return devices
