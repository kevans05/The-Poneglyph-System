import threading
from .pmm2_interface import PMM2Driver

# ── Module-level connection state ─────────────────────────────────────────────
#
# PMM1 is a serial instrument and is now driven entirely in the browser via the
# Web Serial API (static/pmm-webserial.js).  Only PMM2 (TCP/IP) is handled here.

_lock = threading.Lock()
_active = None       # PMM2Driver instance, or None
_active_model = None  # "pmm2" | None


# ── Module-level API helpers (used by api.py) ─────────────────────────────────

def api_connect(port: str, model: str = "pmm2") -> dict:
    global _active, _active_model
    with _lock:
        if _active and _active.is_connected:
            _active.disconnect()

        if model != "pmm2":
            return {"ok": False, "error": f"Unsupported meter model '{model}' — "
                                          f"PMM1 connects via Web Serial in the browser"}

        # For PMM2, 'port' is the IP address (optionally "ip:port").
        ip = port
        tcp_port = 5025
        if ":" in port:
            ip, p_str = port.split(":")
            tcp_port = int(p_str)

        drv = PMM2Driver(ip, tcp_port)
        result = drv.connect()
        if result["ok"]:
            _active = drv
            _active_model = "pmm2"
        return result

def api_configure(chan1: int, chan2: int) -> dict:
    with _lock:
        if not _active or not _active.is_connected:
            return {"ok": False, "error": "Not connected"}
        return _active.configure_channels(chan1, chan2)

def api_query() -> dict:
    with _lock:
        if not _active or not _active.is_connected:
            return {"ok": False, "error": "Not connected"}
        return _active.query()

def api_disconnect() -> dict:
    global _active, _active_model
    with _lock:
        if _active:
            _active.disconnect()
            _active = None
            _active_model = None
        return {"ok": True}

def api_status() -> dict:
    with _lock:
        if _active and _active.is_connected:
            pname = getattr(_active, "port", None) or getattr(_active, "port_name", None)
            return {"connected": True, "model": _active_model, "port": pname}
        return {"connected": False, "model": None, "port": None}
