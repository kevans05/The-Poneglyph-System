import threading
from .pmm1_interface import PMM1Driver, list_ports
from .pmm2_interface import PMM2Driver
from .sim_driver import SimulationDriver

# ── Module-level connection state ─────────────────────────────────────────────

_lock = threading.Lock()
_active = None       # Driver instance (PMM1Driver, PMM2Driver, or SimulationDriver)
_active_model = None  # "pmm1" | "pmm2" | "sim" | None


# ── Module-level API helpers (used by api.py) ─────────────────────────────────

def api_list_ports():
    """Return serial ports for PMM1."""
    return list_ports()

def api_connect(port: str, model: str = "pmm1") -> dict:
    global _active, _active_model
    with _lock:
        if _active and _active.is_connected:
            _active.disconnect()
        
        if model == "sim":
            drv = SimulationDriver("PMM Simulator")
            result = drv.connect()
            if result["ok"]:
                _active = drv
                _active_model = "sim"
            return result
        elif model == "pmm2":
            # For PMM2, 'port' is the IP address
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
        else:
            drv = PMM1Driver(port)
            result = drv.connect()
            if result["ok"]:
                _active = drv
                _active_model = "pmm1"
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
