import math
from ..voltage_phasor import VoltagePhasor
from ..current_phasor import CurrentPhasor
from ..wye_system import wye_currents, wye_voltages
from ..utilities.power_utilities import append_3phase_details

class VoltageRegulator:
    """
    A 3-phase Step Voltage Regulator.
    Typically has 32 steps (16 boost, 16 buck), each 0.625%, for a +/- 10% range.
    """
    def __init__(
        self,
        name: str,
        nominal_kv: float,
        tap_pos: int = 0,  # Range -16 to +16
        step_percent: float = 0.625,
        max_steps: int = 16
    ):
        self.name = name
        self.nominal_kv = nominal_kv
        self.tap_pos = max(-max_steps, min(tap_pos, max_steps))
        self.step_percent = step_percent
        self.max_steps = max_steps
        self.upstream_device = None
        self.connections = []
        self._cache = {}
        self._evaluating = False

    @property
    def ratio(self) -> float:
        return 1.0 / (1.0 + (self.tap_pos * self.step_percent / 100.0))

    def connect(self, downstream_device, **kwargs):
        if downstream_device not in self.connections:
            self.connections.append(downstream_device)
        downstream_device.upstream_device = self
        return downstream_device

    @property
    def connection_type(self) -> str:
        if self.upstream_device:
            return getattr(
                self.upstream_device, "downstream_connection_type",
                getattr(self.upstream_device, "connection_type", "wye"),
            )
        return "wye"

    @property
    def downstream_connection_type(self) -> str:
        return self.connection_type

    @property
    def voltage(self):
        if "voltage" in self._cache: return self._cache["voltage"]
        if self._evaluating: return None
        self._evaluating = True
        try:
            up_v = None
            if self.upstream_device:
                if hasattr(self.upstream_device, "downstream_voltage"):
                    up_v = self.upstream_device.downstream_voltage
                else:
                    up_v = getattr(self.upstream_device, "voltage", None)
            
            if not up_v: return None
            
            r = self.ratio
            def xform_v(p):
                return VoltagePhasor(p.magnitude / r, p.angle_degrees)
            
            res = wye_voltages(xform_v(up_v.a), xform_v(up_v.b), xform_v(up_v.c))
            self._cache["voltage"] = res; return res
        finally:
            self._evaluating = False

    @property
    def downstream_voltage(self):
        return self.voltage

    @property
    def current(self):
        if "current" in self._cache: return self._cache["current"]
        if self._evaluating: return None
        self._evaluating = True
        try:
            up_i = None
            if self.upstream_device:
                if hasattr(self.upstream_device, "downstream_current"):
                    up_i = self.upstream_device.downstream_current
                else:
                    up_i = getattr(self.upstream_device, "current", None)
            
            if not up_i: return None
            
            r = self.ratio
            def xform_i(p):
                return CurrentPhasor(p.magnitude * r, p.angle_degrees)
            
            res = wye_currents(xform_i(up_i.a), xform_i(up_i.b), xform_i(up_i.c))
            self._cache["current"] = res; return res
        finally:
            self._evaluating = False

    @property
    def downstream_current(self):
        return self.current

    def get_summary_dict(self):
        boost_buck = "Boost" if self.tap_pos > 0 else "Buck" if self.tap_pos < 0 else "Neutral"
        regulation = self.tap_pos * self.step_percent
        is_delta = self.connection_type == "delta"
        
        stats = {
            "Type": "Voltage Regulator",
            "Nominal kV": self.nominal_kv,
            "Tap Position": f"{self.tap_pos} ({boost_buck})",
            "Regulation": f"{regulation:+.3f}%",
            "Ratio": f"{1.0/self.ratio:.4f}",
            "Connection": "Delta (Δ)" if is_delta else "Wye (Y)",
        }
        
        if not self.voltage:
            stats["Status"] = "DEAD (Disconnected)"
            
        return append_3phase_details(stats, self.voltage, self.current, is_delta=is_delta)
