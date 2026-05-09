from ..wye_system import wye_currents, wye_voltages
from ..current_phasor import CurrentPhasor
from ..voltage_phasor import VoltagePhasor
from ..utilities.power_utilities import append_3phase_details
import cmath
import math

class ProtectionDevice:
    def __init__(self, name: str):
        self.name = name
        self.inputs = []
        self.secondary_connections = []
        self._evaluating = False

    def add_input(self, source_device):
        if source_device not in self.inputs:
            self.inputs.append(source_device)
        return self

    def connect(self, downstream_device, **kwargs):
        if downstream_device not in self.secondary_connections:
            self.secondary_connections.append(downstream_device)
            if hasattr(downstream_device, 'add_input'):
                downstream_device.add_input(self)
        return downstream_device

    def connect_secondary(self, downstream_device):
        return self.connect(downstream_device)

    @property
    def current(self):
        if self._evaluating: return None
        self._evaluating = True
        try:
            total_a = complex(0)
            total_b = complex(0)
            total_c = complex(0)
            found = False
            for src in self.inputs:
                # Sum currents from all connected CTs/CTTBs
                i_sys = getattr(src, 'secondary_current', None)
                if i_sys:
                    total_a += i_sys.a.to_complex()
                    total_b += i_sys.b.to_complex()
                    total_c += i_sys.c.to_complex()
                    found = True
            if not found: return None
            def from_complex(c):
                mag, ang_rad = cmath.polar(c)
                return CurrentPhasor(mag, math.degrees(ang_rad))
            return wye_currents(from_complex(total_a), from_complex(total_b), from_complex(total_c))
        finally:
            self._evaluating = False

    @property
    def voltage(self):
        if self._evaluating: return None
        self._evaluating = True
        try:
            total_a = complex(0)
            total_b = complex(0)
            total_c = complex(0)
            found = False
            for src in self.inputs:
                v_sys = getattr(src, 'secondary_voltage', None)
                if not v_sys:
                    v_sys = getattr(src, 'secondary2_voltage', None)
                if v_sys:
                    total_a += v_sys.a.to_complex()
                    total_b += v_sys.b.to_complex()
                    total_c += v_sys.c.to_complex()
                    found = True
            if not found: return None
            count = len([i for i in self.inputs if hasattr(i, 'secondary_voltage') or hasattr(i, 'secondary2_voltage')])
            if count > 1:
                total_a /= count
                total_b /= count
                total_c /= count
            def from_complex(c):
                mag, ang_rad = cmath.polar(c)
                return VoltagePhasor(mag, math.degrees(ang_rad))
            return wye_voltages(from_complex(total_a), from_complex(total_b), from_complex(total_c))
        finally:
            self._evaluating = False

    @property
    def secondary_current(self): return self.current
    
    @property
    def secondary_voltage(self): return self.voltage

    def get_summary_dict(self):
        stats = {"Type": self.__class__.__name__, "Inputs": len(self.inputs)}
        if not self.inputs: stats["Status"] = "No Input Sources"
        return append_3phase_details(stats, self.voltage, self.current)

class CTTB(ProtectionDevice):
    def __init__(self, name: str, mode: str = "SUM"):
        super().__init__(name)
        self.mode = mode.upper().strip()

    @property
    def current(self):
        if self._evaluating: return None
        self._evaluating = True
        try:
            total_a = complex(0)
            total_b = complex(0)
            total_c = complex(0)
            found = False

            for i, src in enumerate(self.inputs):
                i_sys = getattr(src, 'secondary_current', None)
                if i_sys:
                    # In differential protection, we usually sum all currents
                    # entering the zone. If CTs are all facing 'AWAY' from the bus,
                    # then Sum(I) = I_differential.
                    # If the user specifically selected 'DIFFERENTIAL' mode,
                    # we perform I1 - I2 - I3... as requested.
                    if self.mode == "DIFFERENTIAL" and i > 0:
                        total_a -= i_sys.a.to_complex()
                        total_b -= i_sys.b.to_complex()
                        total_c -= i_sys.c.to_complex()
                    else:
                        total_a += i_sys.a.to_complex()
                        total_b += i_sys.b.to_complex()
                        total_c += i_sys.c.to_complex()
                    found = True

            if not found: return None

            def from_complex(c):
                mag, ang_rad = cmath.polar(c)
                return CurrentPhasor(mag, math.degrees(ang_rad))

            return wye_currents(from_complex(total_a), from_complex(total_b), from_complex(total_c))
        finally:
            self._evaluating = False

    def get_summary_dict(self):
        stats = super().get_summary_dict()
        stats["Mode"] = self.mode

        # Add differential specific metrics if in that mode
        if self.mode == "DIFFERENTIAL":
            i_diff = self.current
            if i_diff:
                stats["--- DIFF METRICS ---"] = "HEADER"
                stats["Idiff Phase A"] = f"{i_diff.a.magnitude:.3f} A"

                # Calculate restraint current (approximate as max mag for now)
                mags = []
                for src in self.inputs:
                    i_sys = getattr(src, 'secondary_current', None)
                    if i_sys: mags.append(i_sys.a.magnitude)
                if mags:
                    stats["Irestraint (Max)"] = f"{max(mags):.3f} A"

        return stats
class FTBlock(ProtectionDevice):
    pass

class IsoBlock(FTBlock):
    """Isolation block — voltage path device identical to FTBlock."""
    pass

class Relay(ProtectionDevice):
    def __init__(self, name: str, function: str = "Differential", input_polarities: dict = None):
        super().__init__(name)
        self.function = function
        self.input_polarities = input_polarities or {}

    @property
    def current(self):
        if self._evaluating: return None
        self._evaluating = True
        try:
            total_a = complex(0)
            total_b = complex(0)
            total_c = complex(0)
            found = False
            for src in self.inputs:
                i_sys = getattr(src, 'secondary_current', None)
                if i_sys:
                    sign = self.input_polarities.get(src.name, 1)
                    total_a += sign * i_sys.a.to_complex()
                    total_b += sign * i_sys.b.to_complex()
                    total_c += sign * i_sys.c.to_complex()
                    found = True
            if not found: return None
            def from_complex(c):
                mag, ang_rad = cmath.polar(c)
                return CurrentPhasor(mag, math.degrees(ang_rad))
            return wye_currents(from_complex(total_a), from_complex(total_b), from_complex(total_c))
        finally:
            self._evaluating = False

    def get_summary_dict(self):
        i_result = self.current
        v_result = self.voltage
        stats = {"Type": self.__class__.__name__, "Inputs": len(self.inputs)}
        if not self.inputs:
            stats["Status"] = "No Input Sources"
        stats = append_3phase_details(stats, v_result, i_result)
        stats["Function"] = self.function

        if self.input_polarities:
            for src in self.inputs:
                pol = self.input_polarities.get(src.name, 1)
                stats[f"  {src.name} polarity"] = "+" if pol == 1 else "−"

        if i_result and len(self.inputs) > 1:
            mags = [i_sys.a.magnitude for src in self.inputs
                    if (i_sys := getattr(src, "secondary_current", None))]
            if mags:
                stats["Irestraint (Max)"] = max(mags)
                stats["Idiff Phase A"] = i_result.a.magnitude

        return stats

class AuxiliaryTransformer(ProtectionDevice):
    def __init__(self, name: str, phase_shift_deg: float = 0.0, ratio: float = 1.0):
        super().__init__(name)
        self.phase_shift_deg = phase_shift_deg
        self.ratio = ratio

    def _apply_shift(self, system):
        if not system: return None
        rotation = cmath.rect(1, math.radians(self.phase_shift_deg))
        
        def process(p):
            new_c = (p.to_complex() * self.ratio) * rotation
            mag, ang = cmath.polar(new_c)
            if isinstance(p, VoltagePhasor):
                return VoltagePhasor(mag, math.degrees(ang))
            return CurrentPhasor(mag, math.degrees(ang))
            
        return type(system)(process(system.a), process(system.b), process(system.c))

    @property
    def current(self):
        base_i = super().current
        return self._apply_shift(base_i)

    @property
    def voltage(self):
        base_v = super().voltage
        return self._apply_shift(base_v)

    def get_summary_dict(self):
        stats = super().get_summary_dict()
        stats["Phase Shift"] = f"{self.phase_shift_deg:+.1f}°"
        stats["Ratio Correction"] = f"{self.ratio:.4f}"
        return stats

class Meter(ProtectionDevice):
    def get_summary_dict(self):
        stats = super().get_summary_dict()
        v = self.voltage
        i = self.current
        if v and i:
            def calc_pq(vp, ip):
                v_c = vp.to_complex()
                i_c = ip.to_complex()
                s_c = v_c * i_c.conjugate()
                return s_c.real, s_c.imag

            p_a, q_a = calc_pq(v.a, i.a)
            p_b, q_b = calc_pq(v.b, i.b)
            p_c, q_c = calc_pq(v.c, i.c)
            
            p_total = p_a + p_b + p_c
            q_total = q_a + q_b + q_c
            s_total = math.sqrt(p_total**2 + q_total**2)
            pf = p_total / s_total if s_total > 0 else 1.0
            
            stats["--- POWER METRICS ---"] = "HEADER"
            stats["Total Active Power"] = p_total
            stats["Total Reactive Power"] = q_total
            stats["Total Apparent Power"] = s_total
            stats["System PF"] = f"{pf:.3f}"
        return stats
