from .protection import ProtectionDevice
import cmath
import math

from ..current_phasor import CurrentPhasor
from ..utilities.formatter import SIPrefix
from ..voltage_phasor import VoltagePhasor
from ..wye_system import wye_currents, wye_voltages


class InstrumentTransformer(ProtectionDevice):
    def __init__(self, name, location, tap_ratios, selected_tap, polarity_normal=True, phase_shift_deg=0.0):
        super().__init__(name)
        self.location = location
        self.tap_ratios = tap_ratios
        self.selected_tap = selected_tap
        self.polarity_normal = polarity_normal
        self.phase_shift_deg = phase_shift_deg
        self.winding_side = "Unknown"

    @property
    def ratio(self):
        return self.tap_ratios[self.selected_tap]

    def _apply_logic(self, system, to_secondary=True, ratio_override=None):
        if not system or not system.is_energized(): return system
        r = ratio_override if ratio_override is not None else self.ratio
        factor = (1 / r) if to_secondary else r
        total_shift = self.phase_shift_deg + (0 if self.polarity_normal else 180)
        rotation_vector = cmath.rect(1, math.radians(total_shift))

        def process_phasor(p):
            new_complex = (p.to_complex() * factor) * rotation_vector
            mag, ang_rad = cmath.polar(new_complex)
            if isinstance(p, VoltagePhasor):
                return VoltagePhasor(mag, math.degrees(ang_rad))
            return CurrentPhasor(mag, math.degrees(ang_rad))

        return type(system)(
            process_phasor(system.a), process_phasor(system.b), process_phasor(system.c)
        )

    def auto_configure(self, host_device):
        if not host_device: return
        bushing = getattr(self, "bushing", "X").upper()
        if host_device.__class__.__name__ == "PowerTransformer":
            self.winding_side = "Primary (High Side)" if bushing in ("H", "Y", "PRIMARY") else "Secondary (Low Side)"
        else:
            self.winding_side = "Standard Terminal"

    # Sensors should ONLY report their specific domain.
    # CTs report Current, VTs report Voltage.
    @property
    def current(self):
        """Returns the primary-side current for this transformer."""
        if "current" in self._cache: return self._cache["current"]
        if getattr(self, '_evaluating_sensor_current', False): return wye_currents()
        self._evaluating_sensor_current = True
        try:
            # First check analog chain (cascaded CTs)
            if self.inputs:
                res = super().current 
                if res and res.is_energized():
                    self._cache["current"] = res; return res

            # Fallback to physical host (upstream_device)
            if self.upstream_device:
                # We need to know which quantity of the host to look at.
                # If we are a CT, we always look at the host's current.
                b = getattr(self, "bushing", "X").upper()
                if b in ("H", "Y", "PRIMARY") and hasattr(self.upstream_device, "primary_current"):
                    res = self.upstream_device.primary_current
                elif hasattr(self.upstream_device, "secondary_current"):
                    res = self.upstream_device.secondary_current
                else:
                    res = getattr(self.upstream_device, "downstream_current", getattr(self.upstream_device, "current", None))
                
                if res:
                    self._cache["current"] = res; return res
            return wye_currents()
        finally:
            self._evaluating_sensor_current = False

    @property
    def voltage(self):
        """Returns the primary-side voltage for this transformer."""
        if "voltage" in self._cache: return self._cache["voltage"]
        if getattr(self, '_evaluating_sensor_voltage', False): return wye_voltages()
        self._evaluating_sensor_voltage = True
        try:
            if self.inputs:
                res = super().voltage
                if res and res.is_energized():
                    self._cache["voltage"] = res; return res

            if self.upstream_device:
                b = getattr(self, "bushing", "X").upper()
                if b in ("H", "Y", "PRIMARY") and hasattr(self.upstream_device, "primary_voltage"):
                    res = self.upstream_device.primary_voltage
                elif hasattr(self.upstream_device, "secondary_voltage"):
                    res = self.upstream_device.secondary_voltage
                else:
                    res = getattr(self.upstream_device, "downstream_voltage", getattr(self.upstream_device, "voltage", None))
                
                if res:
                    self._cache["voltage"] = res; return res
            return wye_voltages()
        finally:
            self._evaluating_sensor_voltage = False


SECONDARY_WIRINGS = {
    "Y": "Y — Wye (Standard)",
    "DAB": "Δ — Delta (DAB)",
    "DAC": "Δ — Delta (DAC)",
    "RESIDUAL": "3I₀ — Residual",
    "A": "Phase A Only",
    "B": "Phase B Only",
    "C": "Phase C Only",
    "N": "Neutral / Ground",
}

VT_SECONDARY_WIRINGS = {
    "Y": "Y — Wye (LN)",
    "D": "Δ — Delta (LL)",
    "DAB": "Δ — Delta (DAB)",
    "DAC": "Δ — Delta (DAC)",
}


class CurrentTransformer(InstrumentTransformer):
    def __init__(self, name, location, tap_ratios, selected_tap, bushing="X", polarity_facing="AWAY", 
                 position="inner", polarity_normal=True, phase_shift_deg=0.0, secondary_wiring="Y", phase_ratios=None):
        super().__init__(name, location, tap_ratios, selected_tap, polarity_normal, phase_shift_deg)
        self.bushing, self.polarity_facing, self.position = bushing.upper(), polarity_facing.upper(), position.lower()
        sw = secondary_wiring.upper().strip()
        self.secondary_wiring = sw if sw in SECONDARY_WIRINGS else "Y"
        self.phase_ratios = phase_ratios or {}

    @property
    def is_reversed(self):
        if self.bushing == "X": return self.polarity_facing == "TOWARDS"
        return self.polarity_facing == "AWAY" if self.bushing in ("Y", "H") else False

    def _apply_secondary_wiring(self, i_sys):
        def _sub(p1, p2):
            c = p1.to_complex() - p2.to_complex(); mag, ang = cmath.polar(c)
            return CurrentPhasor(mag, math.degrees(ang))
        if self.secondary_wiring in ("DAB", "D"):
            return wye_currents(_sub(i_sys.a, i_sys.b), _sub(i_sys.b, i_sys.c), _sub(i_sys.c, i_sys.a))
        elif self.secondary_wiring == "DAC":
            return wye_currents(_sub(i_sys.a, i_sys.c), _sub(i_sys.c, i_sys.b), _sub(i_sys.b, i_sys.a))
        elif self.secondary_wiring == "RESIDUAL":
            i_res = i_sys.a + i_sys.b + i_sys.c
            return wye_currents(i_res, i_res, i_res)
        elif self.secondary_wiring == "A": return wye_currents(i_sys.a, CurrentPhasor(0,0), CurrentPhasor(0,0))
        elif self.secondary_wiring == "B": return wye_currents(CurrentPhasor(0,0), i_sys.b, CurrentPhasor(0,0))
        elif self.secondary_wiring == "C": return wye_currents(CurrentPhasor(0,0), CurrentPhasor(0,0), i_sys.c)
        elif self.secondary_wiring == "N": return wye_currents(neutral=(i_sys.a + i_sys.b + i_sys.c))
        return i_sys

    @property
    def secondary_current(self):
        source_i = self.current
        if source_i and source_i.is_energized():
            def scale(p, ph):
                r = self.phase_ratios.get(ph)
                if r is None: return p
                return CurrentPhasor(p.magnitude * self.ratio / r, p.angle_degrees)
            base = self._apply_logic(source_i, to_secondary=True)
            base = wye_currents(scale(base.a, "a"), scale(base.b, "b"), scale(base.c, "c"))
            return self._apply_secondary_wiring(base)
        return wye_currents()

    def get_summary_dict(self):
        stats = {"Location": self.location, "Type": "CT", "Ratio": f"{self.ratio}:1", "Bushing": self.bushing}
        if getattr(self, "fault_state", None):
            stats["--- FAULT ACTIVE ---"] = "HEADER"
            stats["Fault Type"] = self.fault_state.get("fault_type")
        sec_i = self.secondary_current
        from ..utilities.power_utilities import append_3phase_details
        return append_3phase_details(stats, None, sec_i) # ONLY CURRENT


class VoltageTransformer(InstrumentTransformer):
    def __init__(self, name, location, tap_ratios, selected_tap, bushing="X", polarity_normal=True, phase_shift_deg=0.0, secondary_wiring="Y"):
        super().__init__(name, location, tap_ratios, selected_tap, polarity_normal, phase_shift_deg)
        self.bushing = bushing.upper()
        sw = secondary_wiring.upper().strip()
        self.secondary_wiring = sw if sw in VT_SECONDARY_WIRINGS else "Y"

    @property
    def secondary_voltage(self):
        source_v = self.voltage
        if source_v and source_v.is_energized():
            base = self._apply_logic(source_v, to_secondary=True)
            def _sub(p1, p2):
                c = p1.to_complex() - p2.to_complex(); mag, ang = cmath.polar(c)
                return VoltagePhasor(mag, math.degrees(ang))
            if self.secondary_wiring in ("DAB", "D"):
                return wye_voltages(_sub(base.a, base.b), _sub(base.b, base.c), _sub(base.c, base.a))
            elif self.secondary_wiring == "DAC":
                return wye_voltages(_sub(base.a, base.c), _sub(base.c, base.b), _sub(base.b, base.a))
            return base
        return wye_voltages()

    def get_summary_dict(self):
        stats = {"Location": self.location, "Type": "VT", "Ratio": f"{self.ratio}:1", "Bushing": self.bushing}
        sec_v = self.secondary_voltage
        from ..utilities.power_utilities import append_3phase_details
        return append_3phase_details(stats, sec_v, None, is_delta=(self.secondary_wiring in ("D", "DAB", "DAC")))


class DualWindingVT(VoltageTransformer):
    def __init__(self, name, location, tap_ratios, selected_tap, sec2_ratio, bushing="X", polarity_normal=True, phase_shift_deg=0.0, secondary_wiring="Y", secondary2_wiring="Y"):
        super().__init__(name, location, tap_ratios, selected_tap, bushing, polarity_normal, phase_shift_deg, secondary_wiring)
        self.sec2_ratio = sec2_ratio
        sw2 = secondary2_wiring.upper().strip()
        self.secondary2_wiring = sw2 if sw2 in VT_SECONDARY_WIRINGS else "Y"

    @property
    def secondary2_voltage(self):
        source_v = self.voltage
        if source_v and source_v.is_energized():
            base = self._apply_logic(source_v, to_secondary=True, ratio_override=self.sec2_ratio)
            def _sub(p1, p2):
                c = p1.to_complex() - p2.to_complex(); mag, ang = cmath.polar(c)
                return VoltagePhasor(mag, math.degrees(ang))
            if self.secondary2_wiring in ("DAB", "D"):
                return wye_voltages(_sub(base.a, base.b), _sub(base.b, base.c), _sub(base.c, base.a))
            elif self.secondary2_wiring == "DAC":
                return wye_voltages(_sub(base.a, base.c), _sub(base.c, base.b), _sub(base.b, base.a))
            return base
        return wye_voltages()

    def get_summary_dict(self):
        stats = super().get_summary_dict()
        stats["Type"] = "Dual Winding VT"
        sec2_v = self.secondary2_voltage
        from ..utilities.power_utilities import append_3phase_details
        stats["--- WINDING 2 ---"] = "HEADER"
        return append_3phase_details(stats, sec2_v, None, is_delta=(self.secondary2_wiring in ("D", "DAB", "DAC")))
