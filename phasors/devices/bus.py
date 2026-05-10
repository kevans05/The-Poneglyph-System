from ..current_phasor import CurrentPhasor
import cmath
import math

from ..phasor_operations import voltage_current_multiplier
from ..utilities.power_utilities import append_3phase_details
from ..wye_system import wye_currents, wye_voltages


class Bus:
    def __init__(self, name: str, nominal_voltage=None, nominal_current=None):
        self._cache = {}
        self.name = name
        self._voltage = nominal_voltage
        self._current = nominal_current
        self.upstream_device = None
        self.connections = []
        self.h_connections = []
        self.x_connections = []
        self._evaluating = False

    @property
    def voltage(self):
        if "voltage" in self._cache: return self._cache["voltage"]
        if self._voltage: return self._voltage
        if self._evaluating: return None
        self._evaluating = True
        try:
            res = None
            if self.upstream_device:
                res = getattr(self.upstream_device, "downstream_voltage", getattr(self.upstream_device, "voltage", None))
            self._cache["voltage"] = res
            return res
        finally: self._evaluating = False

    

    @property
    def downstream_voltage(self):
        return self.voltage

    @property
    def downstream_current(self):
        return self.current

    @property
    def connection_type(self) -> str:
        if self._evaluating:
            return "wye"
        self._evaluating = True
        try:
            if self.upstream_device:
                return getattr(
                    self.upstream_device,
                    "downstream_connection_type",
                    getattr(self.upstream_device, "connection_type", "wye"),
                )
            return "wye"
        finally:
            self._evaluating = False

    @property
    def downstream_connection_type(self) -> str:
        return self.connection_type

    def connect(self, downstream_device, to_bushing=None, **kwargs):
        if downstream_device not in self.connections:
            self.connections.append(downstream_device)

        # Avoid setting upstream_device if it creates a cycle?
        # For now, just set it and let _evaluating handle it.
        downstream_device.upstream_device = self
        return downstream_device

    

    

    def get_summary_dict(self):
        stats = {"Type": "Bus", "Connections": len(self.connections)}
        return append_3phase_details(stats, self.voltage, self.current)

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

    def sim_step(self, sim_time_ms):
        return self._sim_step_fault(sim_time_ms)

    def find_downstream_impacts(self):
        """Crawl downstream from THIS device to find all connected Loads and active Faults."""
        visited = set()
        loads = []
        faults = []

        def check(dev, current_mask):
            if dev in visited: return
            visited.add(dev)
            
            # Stop at voltage sources (don't back-feed for now)
            if dev.__class__.__name__ == "VoltageSource": return
            
            # Check for active fault on this device
            if getattr(dev, "fault_state", None):
                faults.append((dev, current_mask))

            from .source_load import Load
            if isinstance(dev, Load):
                loads.append((dev, current_mask))
                return
            
            # Update mask based on switch status
            new_mask = current_mask.copy()
            if hasattr(dev, "is_ph_closed"):
                for ph in "abc":
                    if not dev.is_ph_closed(ph):
                        new_mask[ph] = False
            elif hasattr(dev, "is_closed") and not dev.is_closed:
                for ph in "abc": new_mask[ph] = False
            
            if not any(new_mask.values()): return

            # Determine which attributes represent "downstream" for this device
            attrs = ["connections"]
            if dev.__class__.__name__ == "PowerTransformer":
                attrs = ["x_connections"] # Only crawl secondary side
            elif hasattr(dev, "x_connections") and not hasattr(dev, "h_connections"):
                attrs = ["x_connections"]
            elif hasattr(dev, "h_connections"):
                # If we entered via H, we crawl X. 
                # For simplicity, if it has both, we assume X is downstream.
                attrs = ["x_connections", "connections"]
            
            for attr in attrs:
                for c in getattr(dev, attr, []):
                    check(c, new_mask)
            
            if hasattr(dev, "downstream_device") and dev.downstream_device:
                check(dev.downstream_device, new_mask)
            
            # Secondary connections (analog) don't carry primary power


        check(self, {"a": True, "b": True, "c": True})
        return loads, faults

    @property
    def current(self):
        """Calculate current flowing through this device based on DOWNSTREAM loads and faults."""
        if "current" in self._cache: return self._cache["current"]
        if self._evaluating: return None
        self._evaluating = True
        try:
            # Special case: If we are a source, we use our own voltage.
            # If not, we still need a voltage reference to do power->current.
            v_sys = self.voltage
            if not v_sys: return None

            loads, faults = self.find_downstream_impacts()
            if not loads and not faults: return None

            phase_s = {"a": complex(0), "b": complex(0), "c": complex(0)}

            for load, mask in loads:
                pq = load.get_phase_pq()
                for ph in ("a", "b", "c"):
                    if mask[ph]:
                        phase_s[ph] += complex(pq[ph][0], pq[ph][1])

            for f_dev, mask in faults:
                fs = f_dev.fault_state
                z = float(fs.get("current_impedance", fs.get("impedance", 0.01)))
                ftype = fs.get("fault_type", "3PH")
                v_local = f_dev.voltage
                if not v_local: continue
                va, vb, vc = v_local.a.to_complex(), v_local.b.to_complex(), v_local.c.to_complex()

                if ftype == "3PH" or ftype == "Symmetric":
                    for ph, v_comp in zip("abc", [va, vb, vc]):
                        if mask[ph]: phase_s[ph] += (abs(v_comp) ** 2) / z
                elif ftype.startswith("SLG"):
                    ph = ftype.split("-")[-1].lower()
                    if mask[ph]:
                        v_comp = {"a": va, "b": vb, "c": vc}[ph]
                        phase_s[ph] += (abs(v_comp) ** 2) / z
                elif ftype.startswith("LLG"):
                    phases = ftype.split("-")[-1].lower()
                    for ph in phases:
                        if mask[ph]:
                            v_comp = {"a": va, "b": vb, "c": vc}[ph]
                            phase_s[ph] += (abs(v_comp) ** 2) / z
                elif ftype.startswith("LL"):
                    pair = ftype.split("-")[-1].lower()
                    if mask[pair[0]] and mask[pair[1]]:
                        v1 = {"a": va, "b": vb, "c": vc}[pair[0]]
                        v2 = {"a": va, "b": vb, "c": vc}[pair[1]]
                        p_ll = (abs(v1 - v2) ** 2) / z
                        phase_s[pair[0]] += p_ll / 2
                        phase_s[pair[1]] += p_ll / 2

            def make_i(ph, v_phasor):
                s = phase_s[ph]
                if s == 0 or v_phasor.magnitude == 0: return CurrentPhasor(0, v_phasor.angle_degrees)
                i_complex = (s / v_phasor.to_complex()).conjugate()
                mag, ang = cmath.polar(i_complex)
                from ..wye_system import wye_currents # check if needed
                return CurrentPhasor(mag, math.degrees(ang))

            from ..wye_system import wye_currents
            ia = make_i("a", v_sys.a); ib = make_i("b", v_sys.b); ic = make_i("c", v_sys.c)
            res = wye_currents(ia, ib, ic)
            self._cache["current"] = res
            return res
        finally:
            self._evaluating = False
