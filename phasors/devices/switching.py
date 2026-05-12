from .bus import Bus
import math
from ..utilities.formatter import SIPrefix
from ..utilities.power_utilities import append_3phase_details
from ..wye_system import wye_voltages, wye_currents

class Switch(Bus):
    def __init__(self, name: str, is_closed: bool = True, is_single_pole: bool = False):
        super().__init__(name)
        self.is_single_pole = is_single_pole
        # Per-phase manual states
        self._manual_closed = {"a": is_closed, "b": is_closed, "c": is_closed}
        
        self.trip_dc_inputs = [] # legacy 3-pole trip
        self.close_dc_inputs = [] # legacy 3-pole close
        self.dc_input_conns = []
        self.dc_output_conns = []
        
        self.h_connections = []
        self.x_connections = []
        self.sensors = []
        self._evaluating_dc = False

    def open(self):
        for ph in 'abc': self._manual_closed[ph] = False
        self._cache.clear()

    def close(self):
        for ph in 'abc': self._manual_closed[ph] = True
        self._cache.clear()

    def _is_ph_tripped(self, ph) -> bool:
        """True if global or phase-specific trip is active."""
        cache_key = f"tripped_{ph}"
        if cache_key in self._cache: return self._cache[cache_key]
        res = False
        for src in self.trip_dc_inputs:
            if getattr(src, "dc_output_state", False) or getattr(src, "dc_status", False):
                res = True; break
        if not res:
            for conn in self.dc_input_conns:
                if conn["to"] in ["TRIP_COIL", f"TRIP_{ph.upper()}"]:
                    if conn["device"].get_terminal_state(conn["from"]):
                        res = True; break
        
        # LATCHING LOGIC: If a trip is detected, permanently update manual state to OPEN.
        # In SIM mode, we handle this timing in sim_step instead.
        if res and self._manual_closed.get(ph, True) and not getattr(self, "is_sim", False):
            self._manual_closed[ph] = False

        self._cache[cache_key] = res
        return res

    def _is_ph_closed(self, ph) -> bool:
        cache_key = f"closed_driven_{ph}"
        if cache_key in self._cache: return self._cache[cache_key]
        res = False
        for src in self.close_dc_inputs:
            if getattr(src, "dc_output_state", False) or getattr(src, "dc_status", False):
                res = True; break
        if not res:
            for conn in self.dc_input_conns:
                if conn["to"] in ["CLOSE_COIL", f"CLOSE_{ph.upper()}"]:
                    if conn["device"].get_terminal_state(conn["from"]):
                        res = True; break
        
        # LATCHING LOGIC: If a close signal is detected, permanently update manual state to CLOSED.
        # In SIM mode, we handle this timing in sim_step instead.
        if res and not self._manual_closed.get(ph, False) and not getattr(self, "is_sim", False):
            self._manual_closed[ph] = True

        self._cache[cache_key] = res
        return res

    def sim_step(self, sim_time_ms):
        fault_events = self._sim_step_fault(sim_time_ms)
        """Simulation-specific logic for timed operations."""
        if not getattr(self, "is_sim", False): return []
        
        # Initialize sim state if needed
        if not hasattr(self, "_sim_pending_ops"):
            self._sim_pending_ops = {} # {phase: {"target": bool, "time": ms}}
            
            self.operating_time_ms = 50.0 if self.__class__.__name__ == "CircuitBreaker" else 1000.0

        events = fault_events
        for ph in 'abc':
            tripped = self._is_ph_tripped(ph)
            closed_driven = self._is_ph_closed(ph)
            
            # If a trip signal is active and we are closed (and not already opening)
            if tripped and self._manual_closed.get(ph, True):
                if self._sim_pending_ops.get(ph, {}).get("target") != False:
                    self._sim_pending_ops[ph] = {"target": False, "time": sim_time_ms + self.operating_time_ms}
            
            # If a close signal is active and we are open (and not already closing)
            elif closed_driven and not self._manual_closed.get(ph, False):
                if self._sim_pending_ops.get(ph, {}).get("target") != True:
                    self._sim_pending_ops[ph] = {"target": True, "time": sim_time_ms + self.operating_time_ms}
            
            # Check if pending operation is complete
            if ph in self._sim_pending_ops:
                op = self._sim_pending_ops[ph]
                if sim_time_ms >= op["time"]:
                    self._manual_closed[ph] = op["target"]
                    del self._sim_pending_ops[ph]
                    self._cache.clear()
                    # Event for the frame buffer
                    events.append({"type": "SWITCH_OP", "delay": 0, "data": {"device_id": self.name, "phase": ph, "state": op["target"]}})
        
        return events

    def is_ph_closed(self, ph) -> bool:
        cache_key = f"is_ph_closed_{ph}"
        if cache_key in self._cache: return self._cache[cache_key]
        
        # First check signals which might trigger a state latch
        tripped = self._is_ph_tripped(ph)
        closed_driven = self._is_ph_closed(ph)
        
        # State is now primarily driven by the latched _manual_closed state
        res = self._manual_closed.get(ph, True)
        
        # However, if the TRIP signal is STILL active, it overrides the manual state (cannot close into a fault)
        if tripped: res = False
        
        self._cache[cache_key] = res
        return res

    @property
    def is_closed(self) -> bool:
        if "is_closed" in self._cache: return self._cache["is_closed"]
        res = all(self.is_ph_closed(p) for p in 'abc')
        self._cache["is_closed"] = res
        return res

    @is_closed.setter
    def is_closed(self, value):
        for ph in 'abc': self._manual_closed[ph] = value
        self._cache.clear()

    @property
    def status(self):
        if "status" in self._cache: return self._cache["status"]
        if self.is_single_pole:
            states = [("A" if self.is_ph_closed("a") else "."), 
                      ("B" if self.is_ph_closed("b") else "."), 
                      ("C" if self.is_ph_closed("c") else ".")]
            res = f"1-POLE [{' '.join(states)}]"
        elif any(self._is_ph_tripped(p) for p in 'abc'): res = "OPEN (Tripped)"
        elif any(self._is_ph_closed(p) for p in 'abc') and not all(self._manual_closed.values()):
            res = "CLOSED (Driven)"
        else: res = "CLOSED" if self.is_closed else "OPEN"
        self._cache["status"] = res
        return res

    @property
    def voltage(self):
        if "voltage" in self._cache: return self._cache["voltage"]
        if getattr(self, '_evaluating_v', False): return wye_voltages()
        self._evaluating_v = True
        try:
            res = None
            if self.upstream_device:
                res = getattr(self.upstream_device, "downstream_voltage", getattr(self.upstream_device, "voltage", None))
            if res is None: res = wye_voltages()
            self._cache["voltage"] = res
            return res
        finally: self._evaluating_v = False

    

    @property
    def downstream_voltage(self):
        v = self.voltage
        if not v: return None
        def ph_v(p, val): return val if self.is_ph_closed(p) else type(val)(0, 0)
        return wye_voltages(ph_v("a", v.a), ph_v("b", v.b), ph_v("c", v.c))

    

    @property
    def connection_type(self) -> str:
        if self.upstream_device:
            return getattr(self.upstream_device, "downstream_connection_type", getattr(self.upstream_device, "connection_type", "wye"))
        return "wye"

    @property
    def downstream_connection_type(self) -> str: return self.connection_type

    def connect(self, downstream_device, to_bushing="X", **kwargs):
        b = to_bushing.upper()
        if b == "H" or b == "Y":
            if downstream_device not in self.h_connections: self.h_connections.append(downstream_device)
        else:
            if downstream_device not in self.x_connections: self.x_connections.append(downstream_device)
        downstream_device.upstream_device = self
        return downstream_device

    def get_terminal_state(self, label=None) -> bool:
        # Recursion Guard: If we are already evaluating DC logic, 
        # return the base manual state to break the loop.
        if getattr(self, '_evaluating_dc', False):
            # Fallback to manual state
            def _cl(p): return self._manual_closed.get(p, True)
            is_all_cl = all(self._manual_closed.values())
            if not label: return is_all_cl
            l = label.upper()
            # 3-Pole Consolidated
            if l in ["52A", "89A"]: return is_all_cl
            if l in ["52B", "89B"]: return not is_all_cl
            # Phase Specific
            if "_" in l:
                p, suffix = l.split("_")[0], l.split("_")[-1]
                ph = p[-1].lower() if len(p) > 1 else p.lower() # handle 52A_A or A_STATUS
                if ph in 'abc':
                    is_p_cl = _cl(ph)
                    if suffix in ["A", "STATUS"]: return is_p_cl
                    if suffix == "B": return not is_p_cl
            return is_all_cl

        self._evaluating_dc = True
        try:
            if not label: return self.is_closed
            l = label.upper()
            # 3-Pole Consolidated
            if l in ["52A", "89A"]: return self.is_closed
            if l in ["52B", "89B"]: return not self.is_closed
            # Phase Specific (e.g. 52A_A, 52B_C, A_STATUS)
            if "_" in l:
                parts = l.split("_")
                # Handle both styles: 52A_A (prefix_phase) and A_STATUS (phase_suffix)
                if len(parts[0]) == 1: ph = parts[0].lower() # A_STATUS
                else: ph = parts[1].lower() # 52A_A
                
                if ph in 'abc':
                    is_p_cl = self.is_ph_closed(ph)
                    if l.startswith("52B") or l.startswith("89B") or l.endswith("B"):
                        return not is_p_cl
                    return is_p_cl
            return self.is_closed
        finally:
            self._evaluating_dc = False

    def _ensure_sim_state(self):
        if not hasattr(self, "_sim_pending_ops"):
            self._sim_pending_ops = {}
            self.operating_time_ms = 50.0 if self.__class__.__name__ == "CircuitBreaker" else 1000.0

    def handle_trip_signal(self, phase="abc", sim_time_ms=0):
        self._ensure_sim_state()
        phases = list("abc") if phase == "abc" else [phase.lower()]
        for ph in phases:
            if self._manual_closed.get(ph, True):
                if self._sim_pending_ops.get(ph, {}).get("target") != False:
                    self._sim_pending_ops[ph] = {"target": False, "time": sim_time_ms + self.operating_time_ms}

    def handle_close_signal(self, phase="abc", sim_time_ms=0):
        self._ensure_sim_state()
        phases = list("abc") if phase == "abc" else [phase.lower()]
        for ph in phases:
            if not self._manual_closed.get(ph, True):
                if self._sim_pending_ops.get(ph, {}).get("target") != True:
                    self._sim_pending_ops[ph] = {"target": True, "time": sim_time_ms + self.operating_time_ms}

    def add_dc_input_conn(self, source_device, from_label=None, to_label=None):
        conn = {"device": source_device, "from": from_label, "to": to_label}
        if conn not in self.dc_input_conns: self.dc_input_conns.append(conn)
        return self

    def connect_dc(self, downstream_device, from_label=None, to_label=None):
        conn = {"device": downstream_device, "from": from_label, "to": to_label}
        if conn not in self.dc_output_conns:
            self.dc_output_conns.append(conn)
            if hasattr(downstream_device, "add_dc_input_conn"):
                downstream_device.add_dc_input_conn(self, from_label, to_label)
        return downstream_device

    def get_summary_dict(self) -> dict:
        is_delta = self.connection_type == "delta"
        stats = {"Status": self.status, "Connection": "Delta (Δ)" if is_delta else "Wye (Y)"}
        if self.is_single_pole: stats["Mode"] = "Single Pole Independent"
        v, i = self.voltage, self.current
        if v: stats["Line Voltage (LL)"] = v.a.magnitude * math.sqrt(3)
        if i: stats["3-Phase Current"] = max(i.a.magnitude, i.b.magnitude, i.c.magnitude)
        return append_3phase_details(stats, v, i, is_delta=is_delta)

class Disconnect(Switch):
    def __str__(self): return f"Disconnect: {self.name:<10} | Status: {self.status}"

class CircuitBreaker(Switch):
    def __init__(self, name: str, continuous_amps: float, interrupt_ka: float, is_closed: bool = True, is_single_pole: bool = False):
        self._cache = {}
        super().__init__(name, is_closed, is_single_pole)
        self.continuous_amps = continuous_amps
        self.interrupt_ka = interrupt_ka
    def get_summary_dict(self) -> dict:
        stats = super().get_summary_dict()
        stats["Continuous Rating"] = self.continuous_amps
        stats["Interrupt Rating"] = f"{self.interrupt_ka} kA"
        return stats

    

    

    def inject_fault(self, data):
        """
        data: {
            "fault_type": str (3PH, SLG-A, LL-AB, etc.),
            "impedance": float,
            "persistence": str (persistent, transient),
            "duration": float (ms),
            "arcing": bool,
            "internal": bool
        }
        """
        self.fault_state = data
        self._fault_start_time = None # Set on first sim_step
        if hasattr(self, "_cache"): self._cache.clear()

    def clear_fault(self):
        self.fault_state = None
        self._fault_start_time = None
        if hasattr(self, "_cache"): self._cache.clear()

    def _sim_step_fault(self, sim_time_ms):
        if not getattr(self, "fault_state", None): return []
        
        fs = self.fault_state
        if self._fault_start_time is None:
            self._fault_start_time = sim_time_ms
        
        elapsed = sim_time_ms - self._fault_start_time
        
        # 1. Handle Transient persistence
        if fs.get("persistence") == "transient":
            duration = float(fs.get("duration", 100.0))
            if elapsed >= duration:
                self.clear_fault()
                return [{"type": "CLEAR_FAULT", "delay": 0, "data": {"device_id": self.name, "reason": "transient_expired"}}]
        
        # 2. Handle Arcing (fluctuating impedance)
        if fs.get("arcing"):
            import random
            base_z = float(fs.get("impedance", 0.01))
            # Arc resistance fluctuates between 1x and 5x base impedance
            fs["current_impedance"] = base_z * (1.0 + random.random() * 4.0)
            if hasattr(self, "_cache"): self._cache.clear()
        else:
            fs["current_impedance"] = fs.get("impedance", 0.01)

        return []
