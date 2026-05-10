from .bus import Bus
import math

from ..current_phasor import CurrentPhasor
from ..utilities.power_utilities import append_3phase_details
from ..voltage_phasor import VoltagePhasor
from ..wye_system import wye_currents, wye_voltages

# ANSI standard: when H and X windings are from different families,
# H leads X by 30° (secondary lags by -30°).
_Y_FAMILY = frozenset({"Y", "YG"})  # Wye (grounded or ungrounded)
_D_FAMILY = frozenset(
    {"D", "Z", "ZG"}
)  # Delta and zigzag (same family for phase shift)

_WINDING_NAMES = {
    "Y": "Wye",
    "YG": "Wye-Grounded",
    "D": "Delta",
    "Z": "Zigzag",
    "ZG": "Zigzag-Grounded",
}

VALID_WINDINGS = list(_WINDING_NAMES.keys())


def _is_cross_family(h: str, x: str) -> bool:
    """True when H and X windings are from different families (Y vs D/Z)."""
    return (h.upper() in _Y_FAMILY) != (x.upper() in _Y_FAMILY)


class PowerTransformer(Bus):
    def __init__(
        self,
        name: str,
        pri_kv: float,
        sec_kv: float,
        h_winding: str = "Y",
        x_winding: str = "D",
        polarity_reversed: bool = False,  # False → -30° (ANSI), True → +30°
        tap_configs: list | None = None,
        selected_tap_index: int = 0,
    ):
        super().__init__(name)
        self.h_winding = h_winding.upper()
        self.x_winding = x_winding.upper()
        self.polarity_reversed = polarity_reversed
        self.h_connections = []
        self.x_connections = []

        if tap_configs:
            self.tap_configs = tap_configs
            idx = max(0, min(selected_tap_index, len(tap_configs) - 1))
            self.selected_tap_index = idx
            tap = tap_configs[idx]
            self.pri_kv = float(tap["pri_kv"])
            self.sec_kv = float(tap["sec_kv"])
        else:
            self.tap_configs = [{"label": "Nominal", "pri_kv": float(pri_kv), "sec_kv": float(sec_kv)}]
            self.selected_tap_index = 0
            self.pri_kv = float(pri_kv)
            self.sec_kv = float(sec_kv)

        self.ratio = self.pri_kv / self.sec_kv

    # ── Winding helpers ──────────────────────────────────────────────────────

    @property
    def phase_shift_deg(self) -> float:
        """Phase shift applied to secondary voltages and currents.
        Same-family windings: always 0°.
        Cross-family (Y↔D, Y↔Z): −30° normal, +30° reversed polarity.
        """
        if not _is_cross_family(self.h_winding, self.x_winding):
            return 0.0
        return +30.0 if self.polarity_reversed else -30.0

    @property
    def x_is_delta(self) -> bool:
        return self.x_winding in _D_FAMILY

    @property
    def h_is_delta(self) -> bool:
        return self.h_winding in _D_FAMILY

    # ── Connection type propagation ──────────────────────────────────────────

    @property
    def connection_type(self) -> str:
        """Connection type on the primary (H) side — inherited from upstream."""
        if getattr(self, '_evaluating_v', False):
            return "wye"
        self._evaluating_v = True
        try:
            if self.upstream_device:
                return getattr(
                    self.upstream_device,
                    "downstream_connection_type",
                    getattr(self.upstream_device, "connection_type", "wye"),
                )
            return "wye"
        finally:
            self._evaluating_v = False

    @property
    def downstream_connection_type(self) -> str:
        """Connection type exposed to devices on the secondary (X) side."""
        return "delta" if self.x_is_delta else "wye"

    # ── Topology ─────────────────────────────────────────────────────────────

    def connect(self, downstream_device, to_bushing="X", **kwargs):
        b = to_bushing.upper()
        if b in ("H", "Y"):
            if downstream_device not in self.h_connections:
                self.h_connections.append(downstream_device)
        else:
            if downstream_device not in self.x_connections:
                self.x_connections.append(downstream_device)
        downstream_device.upstream_device = self
        return downstream_device

    # ── Voltage ──────────────────────────────────────────────────────────────

    @property
    def primary_voltage(self):
        if "primary_voltage" in self._cache: return self._cache["primary_voltage"]
        if self.upstream_device:
            if hasattr(self.upstream_device, "downstream_voltage"):
                res = self.upstream_device.downstream_voltage; self._cache["primary_voltage"] = res; return res
            res = getattr(self.upstream_device, "voltage", None)
            self._cache["primary_voltage"] = res; return res
        return None

    @property
    def secondary_voltage(self):
        if "secondary_voltage" in self._cache: return self._cache["secondary_voltage"]
        up_v = self.primary_voltage
        if not up_v:
            return None
        shift = self.phase_shift_deg

        def xform_v(p):
            return VoltagePhasor(p.magnitude / self.ratio, p.angle_degrees + shift)

        res = wye_voltages(xform_v(up_v.a), xform_v(up_v.b), xform_v(up_v.c))
        self._cache["secondary_voltage"] = res; return res

    @property
    def voltage(self):
        if "voltage" in self._cache: return self._cache["voltage"]
        if getattr(self, '_evaluating_v', False): return None
        self._evaluating_v = True
        try:
            res = self.secondary_voltage
            self._cache["voltage"] = res
            return res
        finally: self._evaluating = False

    @property
    def downstream_voltage(self):
        return self.voltage

    # ── Current ──────────────────────────────────────────────────────────────

    

    # ── Summary ───────────────────────────────────────────────────────────────

    
    
    @property
    def primary_current(self):
        """Current on the High-Side (H) calculated via Power Conservation."""
        if "primary_current" in self._cache: return self._cache["primary_current"]
        v_pri = self.primary_voltage
        if not v_pri: return None
        
        # We use the same downstream impacts as 'current' (X side)
        loads, faults = self.find_downstream_impacts()
        if not loads and not faults: return None

        # Sum total downstream power
        phase_s = {"a": complex(0), "b": complex(0), "c": complex(0)}
        for load, mask in loads:
            pq = load.get_phase_pq()
            for ph in ("a", "b", "c"):
                if mask[ph]: phase_s[ph] += complex(pq[ph][0], pq[ph][1])
        
        # Transformers might have their own faults
        for f_dev, mask in faults:
            fs = f_dev.fault_state
            z = float(fs.get("current_impedance", fs.get("impedance", 0.01)))
            v_local = f_dev.voltage
            if not v_local: continue
            # Sum fault power... (simplified version for now, should ideally match Bus.py)
            # Power conservation handles the ratio/shift automatically because v_local is correct.
            for ph, v_ph in zip("abc", [v_local.a, v_local.b, v_local.c]):
                if mask[ph]: phase_s[ph] += (v_ph.magnitude ** 2) / z

        def make_i(v_phasor, s):
            if s == 0 or v_phasor.magnitude == 0: return CurrentPhasor(0, v_phasor.angle_degrees)
            i_comp = (s / v_phasor.to_complex()).conjugate()
            import cmath
            mag, ang = cmath.polar(i_comp)
            return CurrentPhasor(mag, math.degrees(ang))

        res = wye_currents(make_i(v_pri.a, phase_s["a"]), make_i(v_pri.b, phase_s["b"]), make_i(v_pri.c, phase_s["c"]))
        self._cache["primary_current"] = res
        return res

    @property
    def secondary_current(self):
        """Current on the Low-Side (X). Inherits Bus.current logic (crawls downstream)."""
        return self.current


    def get_summary_dict(self):
        h_name = _WINDING_NAMES.get(self.h_winding, self.h_winding)
        x_name = _WINDING_NAMES.get(self.x_winding, self.x_winding)
        cross = _is_cross_family(self.h_winding, self.x_winding)
        polarity_str = (
            ("Reversed (+30°)" if self.polarity_reversed else "Normal (−30°)")
            if cross
            else "N/A (same family)"
        )
        current_tap = self.tap_configs[self.selected_tap_index]
        tap_label = current_tap.get("label", f"Tap {self.selected_tap_index}")
        stats = {
            "Type": "Power Transformer",
            "HV Winding (H)": h_name,
            "LV Winding (X)": x_name,
            "Polarity": polarity_str,
            "Active Tap": f"{tap_label} ({self.pri_kv} kV / {self.sec_kv} kV)",
            "Phase Shift": f"{self.phase_shift_deg:+.0f}°",
            "Connection": "Delta (Δ)" if self.x_is_delta else "Wye (Y)",
        }
        up_v = self.primary_voltage
        up_i = self.primary_current
        pri_delta = self.h_is_delta
        if up_v or up_i:
            stats["--- PRIMARY SIDE (H) ---"] = "HEADER"
            phases = [("A", "a"), ("B", "b"), ("C", "c")]
            for label, attr in phases:
                if up_v:
                    v = getattr(up_v, attr)
                    key = f"Pri Phase {label} Voltage ({'LL' if pri_delta else 'LN'})"
                    stats[key] = v.magnitude * (math.sqrt(3) if pri_delta else 1.0)
                    stats[f"Pri Phase {label} V-Angle"] = v.angle_degrees
                if up_i:
                    i = getattr(up_i, attr)
                    stats[f"Pri Phase {label} Current"] = i.magnitude
                    stats[f"Pri Phase {label} I-Angle"] = i.angle_degrees
        stats["--- SECONDARY SIDE (X) ---"] = "HEADER"
        sec_v = self.secondary_voltage
        sec_i = self.secondary_current
        if self.x_is_delta:
            v_phases = [("AB", "a", "b"), ("BC", "b", "c"), ("CA", "c", "a")]
            i_phases = [("A", "a"), ("B", "b"), ("C", "c")]
            for (vl, a1, a2), (il, ia) in zip(v_phases, i_phases):
                stats[f"--- PHASE {vl} ---"] = "HEADER"
                if sec_v:
                    v_ll = getattr(sec_v, a1) - getattr(sec_v, a2)
                    stats[f"Sec Voltage Phase {vl}"] = v_ll.magnitude
                    stats[f"Phase {vl} V-Angle"] = v_ll.angle_degrees
                if sec_i:
                    ip = getattr(sec_i, ia)
                    stats[f"Sec Current Phase {il}"] = ip.magnitude
                    stats[f"Phase {il} I-Angle"] = ip.angle_degrees
        else:
            for label, attr in [("A", "a"), ("B", "b"), ("C", "c")]:
                stats[f"--- PHASE {label} ---"] = "HEADER"
                if sec_v:
                    vp = getattr(sec_v, attr)
                    stats[f"Sec Voltage Phase {label}"] = vp.magnitude
                    stats[f"Phase {label} V-Angle"] = vp.angle_degrees
                if sec_i:
                    ip = getattr(sec_i, attr)
                    stats[f"Sec Current Phase {label}"] = ip.magnitude
                    stats[f"Phase {label} I-Angle"] = ip.angle_degrees
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

    def sim_step(self, sim_time_ms):
        return self._sim_step_fault(sim_time_ms)
