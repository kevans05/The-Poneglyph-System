import cmath
import math

from ..current_phasor import CurrentPhasor
from ..utilities.formatter import SIPrefix
from ..voltage_phasor import VoltagePhasor
from ..wye_system import wye_currents, wye_voltages


class InstrumentTransformer:
    def __init__(
        self,
        name: str,
        location: str,
        tap_ratios: dict,
        selected_tap: str,
        polarity_normal: bool = True,
        phase_shift_deg: float = 0.0,
    ):
        self.name = name
        self.location = location
        self.tap_ratios = tap_ratios
        self.selected_tap = selected_tap
        self.polarity_normal = polarity_normal
        self.phase_shift_deg = phase_shift_deg
        self.upstream_device = None
        self.downstream_device = None
        self.primary_device = None
        self._evaluating = False
        self.secondary_connections = []
        self.winding_side = "Unknown"
        self._cache = {}

    @property
    def ratio(self):
        return self.tap_ratios[self.selected_tap]

    @property
    def connection_type(self) -> str:
        if self.upstream_device:
            return getattr(
                self.upstream_device,
                "downstream_connection_type",
                getattr(self.upstream_device, "connection_type", "wye"),
            )
        return "wye"

    def _apply_logic(self, system, to_secondary=True, ratio_override=None):
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

    def connect(self, downstream_device, **kwargs):
        self.downstream_device = downstream_device
        downstream_device.upstream_device = self
        return downstream_device

    def connect_secondary(self, secondary_device):
        if secondary_device not in self.secondary_connections:
            self.secondary_connections.append(secondary_device)
            if hasattr(secondary_device, "add_input"):
                secondary_device.add_input(self)
        return secondary_device

    def auto_configure(self, host_device):
        """Automatically configure based on host device type and bushing."""
        if not host_device:
            return

        # Determine Winding Side
        bushing = getattr(self, "bushing", "X").upper()
        if host_device.__class__.__name__ == "PowerTransformer":
            if bushing in ("H", "Y", "PRIMARY"):
                self.winding_side = "Primary (High Side)"
            else:
                self.winding_side = "Secondary (Low Side)"
        else:
            self.winding_side = "Standard Terminal"

    @property
    def voltage(self):
        if "voltage" in self._cache: return self._cache["voltage"]
        if self._evaluating:
            return None
        self._evaluating = True
        try:
            if self.upstream_device:
                b = getattr(self, "bushing", "X").upper()
                if b in ("H", "Y", "PRIMARY"):
                    if hasattr(self.upstream_device, "primary_voltage"):
                        res = self.upstream_device.primary_voltage; self._cache["voltage"] = res; return res
                else:
                    if hasattr(self.upstream_device, "secondary_voltage"):
                        res = self.upstream_device.secondary_voltage; self._cache["voltage"] = res; return res

                res = getattr(
                    self.upstream_device,
                    'downstream_voltage',
                    getattr(self.upstream_device, 'voltage', None),
                )
                self._cache['voltage'] = res; return res
            return None
        finally:
            self._evaluating = False

    @property
    def current(self):
        if "current" in self._cache: return self._cache["current"]
        if self._evaluating:
            return None
        self._evaluating = True
        try:
            if self.upstream_device:
                b = getattr(self, "bushing", "X").upper()
                if b in ("H", "Y", "PRIMARY"):
                    if hasattr(self.upstream_device, "primary_current"):
                        res = self.upstream_device.primary_current; self._cache["current"] = res; return res
                else:
                    if hasattr(self.upstream_device, "secondary_current"):
                        res = self.upstream_device.secondary_current; self._cache["current"] = res; return res

                res = getattr(
                    self.upstream_device,
                    'downstream_current',
                    getattr(self.upstream_device, 'current', None),
                )
                self._cache['current'] = res; return res
            return None
        finally:
            self._evaluating = False

    @property
    def downstream_voltage(self):
        return self.voltage

    @property
    def downstream_current(self):
        return self.current


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
    VALID_POSITIONS = ("inner", "middle", "outer")

    def __init__(
        self,
        name: str,
        location: str,
        tap_ratios: dict,
        selected_tap: str,
        bushing: str = "X",
        polarity_facing: str = "AWAY",
        position: str = "inner",
        polarity_normal: bool = True,
        phase_shift_deg: float = 0.0,
        secondary_wiring: str = "Y",
        phase_ratios: dict = None, # {"a": 400, "b": 400, "c": 400, "n": 400}
    ):
        super().__init__(
            name,
            location,
            tap_ratios,
            selected_tap,
            polarity_normal=polarity_normal,
            phase_shift_deg=phase_shift_deg,
        )
        self.bushing = bushing.upper().strip()
        self.polarity_facing = polarity_facing.upper().strip()
        self.position = (
            position.lower().strip()
            if position.lower().strip() in self.VALID_POSITIONS
            else "inner"
        )
        sw = secondary_wiring.upper().strip()
        self.secondary_wiring = sw if sw in SECONDARY_WIRINGS else "Y"
        self.phase_ratios = phase_ratios or {}

    @property
    def is_reversed(self):
        if self.bushing == "X":
            return self.polarity_facing == "TOWARDS"
        elif self.bushing == "Y" or self.bushing == "H":
            return self.polarity_facing == "AWAY"
        return False

    def _apply_secondary_wiring(self, i_sys):
        def _sub(p1, p2):
            c = p1.to_complex() - p2.to_complex()
            mag, ang_rad = cmath.polar(c)
            return CurrentPhasor(mag, math.degrees(ang_rad))

        if self.secondary_wiring == "DAB" or self.secondary_wiring == "D":
            return wye_currents(
                _sub(i_sys.a, i_sys.b),
                _sub(i_sys.b, i_sys.c),
                _sub(i_sys.c, i_sys.a),
            )
        elif self.secondary_wiring == "DAC":
            return wye_currents(
                _sub(i_sys.a, i_sys.c),
                _sub(i_sys.c, i_sys.b),
                _sub(i_sys.b, i_sys.a),
            )
        elif self.secondary_wiring == "RESIDUAL":
            c_sum = i_sys.a.to_complex() + i_sys.b.to_complex() + i_sys.c.to_complex()
            mag, ang_rad = cmath.polar(c_sum)
            i_res = CurrentPhasor(mag, math.degrees(ang_rad))
            return wye_currents(i_res, i_res, i_res)
        elif self.secondary_wiring == "A":
            return wye_currents(i_sys.a, CurrentPhasor(0,0), CurrentPhasor(0,0))
        elif self.secondary_wiring == "B":
            return wye_currents(CurrentPhasor(0,0), i_sys.b, CurrentPhasor(0,0))
        elif self.secondary_wiring == "C":
            return wye_currents(CurrentPhasor(0,0), CurrentPhasor(0,0), i_sys.c)
        elif self.secondary_wiring == "N":
            # Assume neutral current is vector sum of primary currents (if no dedicated neutral CT is modeled)
            c_sum = i_sys.a.to_complex() + i_sys.b.to_complex() + i_sys.c.to_complex()
            mag, ang_rad = cmath.polar(c_sum)
            i_n = CurrentPhasor(mag, math.degrees(ang_rad))
            return wye_currents(CurrentPhasor(0,0), CurrentPhasor(0,0), CurrentPhasor(0,0), neutral=i_n)
        else:
            return i_sys

    def _apply_phase_ratios(self, i_sys):
        """Apply per-phase ratio overrides if present."""
        def scale(p, phase):
            r = self.phase_ratios.get(phase)
            if r is None: return p
            # i_sec = i_pri / r
            # logic already applied 1/self.ratio. We need to swap self.ratio for r.
            # So multiply by self.ratio and divide by r.
            return CurrentPhasor(p.magnitude * self.ratio / r, p.angle_degrees)
        
        return wye_currents(
            scale(i_sys.a, "a"),
            scale(i_sys.b, "b"),
            scale(i_sys.c, "c")
        )

    @property
    def secondary_current(self):
        source_i = self.current
        if source_i:
            base = self._apply_logic(source_i, to_secondary=True)
            base = self._apply_phase_ratios(base)
            return self._apply_secondary_wiring(base)
        return None

    def get_summary_dict(self):
        is_delta = self.secondary_wiring in ("D", "DAB", "DAC")
        stats = {
            "Location": self.location,
            "Winding Side": self.winding_side,
            "Type": "CT",
            "Connection": "Delta (Δ)" if is_delta else "Wye (Y)",
            "Ratio": f"{self.ratio}:1",
            "Bushing": self.bushing,
            "Polarity Facing": self.polarity_facing,
            "Effective Polarity": "REVERSED (180° shift)"
            if self.is_reversed
            else "NORMAL",
            "Secondary Wiring": SECONDARY_WIRINGS.get(
                self.secondary_wiring, self.secondary_wiring
            ),
            "Compensation": f"{self.phase_shift_deg} deg",
        }
        sec_i = self.secondary_current
        if sec_i:
            if self.secondary_wiring == "D":
                labels = [("A-B", "a"), ("B-C", "b"), ("C-A", "c")]
            elif self.secondary_wiring == "N":
                labels = [("N", "neutral_current")]
            else:
                labels = [("A", "a"), ("B", "b"), ("C", "c")]
                
            for label, attr in labels:
                p_phasor = getattr(sec_i, attr)
                if p_phasor:
                    stats[f"--- PHASE {label} ---"] = "HEADER"
                    stats[f"Sec Current Phase {label[0]}"] = p_phasor.magnitude
                    stats[f"Phase {label[0]} I-Angle"] = p_phasor.angle_degrees
        else:
            stats["Status"] = "DEAD (No Current)"
        return stats


class VoltageTransformer(InstrumentTransformer):
    def __init__(
        self,
        name: str,
        location: str,
        tap_ratios: dict,
        selected_tap: str,
        bushing: str = "X",
        polarity_normal=True,
        phase_shift_deg=0.0,
        secondary_wiring: str = "Y",
    ):
        super().__init__(
            name, location, tap_ratios, selected_tap, polarity_normal, phase_shift_deg
        )
        self.bushing = bushing.upper().strip()
        sw = secondary_wiring.upper().strip()
        self.secondary_wiring = sw if sw in VT_SECONDARY_WIRINGS else "Y"

    def _apply_secondary_wiring(self, v_sys):
        def _sub(p1, p2):
            c = p1.to_complex() - p2.to_complex()
            mag, ang_rad = cmath.polar(c)
            return VoltagePhasor(mag, math.degrees(ang_rad))

        if self.secondary_wiring in ("DAB", "D"):
            return wye_voltages(
                _sub(v_sys.a, v_sys.b),
                _sub(v_sys.b, v_sys.c),
                _sub(v_sys.c, v_sys.a),
            )
        elif self.secondary_wiring == "DAC":
            return wye_voltages(
                _sub(v_sys.a, v_sys.c),
                _sub(v_sys.c, v_sys.b),
                _sub(v_sys.b, v_sys.a),
            )
        else:
            return v_sys

    @property
    def secondary_voltage(self):
        source_v = self.voltage
        if source_v:
            base = self._apply_logic(source_v, to_secondary=True)
            return self._apply_secondary_wiring(base)
        return None

    def get_summary_dict(self):
        is_delta = self.secondary_wiring in ("D", "DAB", "DAC")
        stats = {
            "Location": self.location,
            "Winding Side": self.winding_side,
            "Type": "VT / PT",
            "Connection": "Delta (Δ)" if is_delta else "Wye (Y)",
            "Ratio": f"{self.ratio}:1",
            "Compensation": f"{self.phase_shift_deg} deg",
            "Bushing": self.bushing,
            "Secondary Wiring": VT_SECONDARY_WIRINGS.get(self.secondary_wiring, self.secondary_wiring),
        }
        sec_v = self.secondary_voltage
        if sec_v:
            if is_delta:
                labels = [("AB", "a"), ("BC", "b"), ("CA", "c")]
                for label, attr in labels:
                    stats[f"--- PHASE {label} ---"] = "HEADER"
                    p_phasor = getattr(sec_v, attr)
                    stats[f"Sec Voltage Phase {label}"] = p_phasor.magnitude
                    stats[f"Phase {label} V-Angle"] = p_phasor.angle_degrees
            else:
                phases = [("A", "a"), ("B", "b"), ("C", "c")]
                for label, attr in phases:
                    stats[f"--- PHASE {label} ---"] = "HEADER"
                    p_phasor = getattr(sec_v, attr)
                    stats[f"Sec Voltage Phase {label}"] = p_phasor.magnitude
                    stats[f"Phase {label} V-Angle"] = p_phasor.angle_degrees
        else:
            stats["Status"] = "DEAD (No Voltage)"
        return stats


class DualWindingVT(VoltageTransformer):
    def __init__(
        self,
        name: str,
        location: str,
        tap_ratios: dict,
        selected_tap: str,
        sec2_ratio: float,
        bushing: str = "X",
        polarity_normal: bool = True,
        phase_shift_deg: float = 0.0,
        secondary_wiring: str = "Y",
        secondary2_wiring: str = "Y",
    ):
        super().__init__(
            name,
            location,
            tap_ratios,
            selected_tap,
            bushing,
            polarity_normal,
            phase_shift_deg,
            secondary_wiring,
        )
        self.sec2_ratio = sec2_ratio
        sw2 = secondary2_wiring.upper().strip()
        self.secondary2_wiring = sw2 if sw2 in VT_SECONDARY_WIRINGS else "Y"

    def _apply_secondary2_wiring(self, v_sys):
        def _sub(p1, p2):
            c = p1.to_complex() - p2.to_complex()
            mag, ang_rad = cmath.polar(c)
            return VoltagePhasor(mag, math.degrees(ang_rad))

        if self.secondary2_wiring in ("DAB", "D"):
            return wye_voltages(
                _sub(v_sys.a, v_sys.b),
                _sub(v_sys.b, v_sys.c),
                _sub(v_sys.c, v_sys.a),
            )
        elif self.secondary2_wiring == "DAC":
            return wye_voltages(
                _sub(v_sys.a, v_sys.c),
                _sub(v_sys.c, v_sys.b),
                _sub(v_sys.b, v_sys.a),
            )
        else:
            return v_sys

    @property
    def secondary2_voltage(self):
        source_v = self.voltage
        if source_v:
            base = self._apply_logic(
                source_v, to_secondary=True, ratio_override=self.sec2_ratio
            )
            return self._apply_secondary2_wiring(base)
        return None

    def get_summary_dict(self):
        stats = super().get_summary_dict()
        is_delta2 = self.secondary2_wiring in ("D", "DAB", "DAC")
        stats["Type"] = "Dual Winding VT"
        stats["Ratio W1"] = f"{self.ratio}:1"
        stats["Ratio W2"] = f"{self.sec2_ratio}:1"
        stats["Secondary 2 Wiring"] = VT_SECONDARY_WIRINGS.get(self.secondary2_wiring, self.secondary2_wiring)

        sec2_v = self.secondary2_voltage
        if sec2_v:
            stats["--- WINDING 2 ---"] = "HEADER"
            if is_delta2:
                labels = [("AB", "a"), ("BC", "b"), ("CA", "c")]
                for label, attr in labels:
                    stats[f"--- PHASE {label} W2 ---"] = "HEADER"
                    p_phasor = getattr(sec2_v, attr)
                    stats[f"Sec2 Voltage Phase {label}"] = p_phasor.magnitude
                    stats[f"Phase {label} W2 V-Angle"] = p_phasor.angle_degrees
            else:
                phases = [("A", "a"), ("B", "b"), ("C", "c")]
                for label, attr in phases:
                    stats[f"--- PHASE {label} W2 ---"] = "HEADER"
                    p_phasor = getattr(sec2_v, attr)
                    stats[f"Sec2 Voltage Phase {label}"] = p_phasor.magnitude
                    stats[f"Phase {label} W2 V-Angle"] = p_phasor.angle_degrees
        return stats
