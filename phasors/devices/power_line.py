from .bus import Bus
from ..wye_system import wye_voltages, wye_currents
from ..phasor_operations import voltage_current_multiplier
from ..utilities.power_utilities import append_3phase_details 
import math

class PowerLine(Bus):
    def __init__(self, name: str, length_km: float = 0.0, r_per_km: float = 0.0, x_per_km: float = 0.0,
                 r0_per_km: float = None, x0_per_km: float = None):
        super().__init__(name)
        self._cache = {}
        self.name = name
        self.length_km = length_km
        self.r_per_km = r_per_km
        self.x_per_km = x_per_km
        # Zero-sequence impedance defaults to 3× positive-sequence (typical overhead line)
        self.r0_per_km = r0_per_km if r0_per_km is not None else r_per_km * 3.0
        self.x0_per_km = x0_per_km if x0_per_km is not None else x_per_km * 3.0
        self.upstream_device = None
        self.downstream_device = None
        

    @property
    def voltage(self):
        if 'voltage' in self._cache: return self._cache['voltage']
        if self._evaluating_v: return None
        self._evaluating_v = True
        try:
            res = None
            if self.upstream_device:
                res = getattr(self.upstream_device, 'downstream_voltage', getattr(self.upstream_device, 'voltage', None))
            self._cache['voltage'] = res
            return res
        finally: self._evaluating_v = False

    @property
    def downstream_voltage(self): return self.voltage
    

    @property
    def connection_type(self) -> str:
        if self.upstream_device:
            return getattr(
                self.upstream_device, 'downstream_connection_type',
                getattr(self.upstream_device, 'connection_type', 'wye'),
            )
        return 'wye'

    @property
    def downstream_connection_type(self) -> str:
        return self.connection_type

    def connect(self, downstream_device, **kwargs):
        self.downstream_device = downstream_device
        downstream_device.upstream_device = self
        return downstream_device

    

    

    def get_summary_dict(self) -> dict:
        is_delta = self.connection_type == 'delta'
        stats = {
            'Type': 'Line',
            'Length (km)': self.length_km,
            'R (Ω/km)': self.r_per_km,
            'X (Ω/km)': self.x_per_km
        }
        up_name = self.upstream_device.name if self.upstream_device else 'Source'
        down_name = self.downstream_device.name if self.downstream_device else 'End of Line'
        stats['Logical Flow'] = f'{up_name} -> [ {self.name} ] -> {down_name}'
        stats['Connection'] = 'Delta (Δ)' if is_delta else 'Wye (Y)'
        v = self.voltage; i = self.current
        if v: stats['Line Voltage (LL)'] = v.a.magnitude * math.sqrt(3)
        if i and v:
            try:
                sa = voltage_current_multiplier(v.a, i.a)
                sb = voltage_current_multiplier(v.b, i.b)
                sc = voltage_current_multiplier(v.c, i.c)
                s_total = sa.complex_power + sb.complex_power + sc.complex_power
                stats['3-Phase Current'] = i.a.magnitude
                stats['Active Power'] = s_total.real
                stats['Reactive Power'] = s_total.imag
                stats['Apparent Power'] = abs(s_total)
            except: pass
        return append_3phase_details(stats, v, i, is_delta=is_delta)

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
