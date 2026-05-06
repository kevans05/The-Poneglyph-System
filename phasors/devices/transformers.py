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


class PowerTransformer:
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
        self.name = name
        self.h_winding = h_winding.upper()
        self.x_winding = x_winding.upper()
        self.polarity_reversed = polarity_reversed
        self.upstream_device = None
        self.h_connections = []
        self.x_connections = []
        self._evaluating = False

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
        if self.upstream_device:
            if hasattr(self.upstream_device, "downstream_voltage"):
                return self.upstream_device.downstream_voltage
            return getattr(self.upstream_device, "voltage", None)
        return None

    @property
    def secondary_voltage(self):
        up_v = self.primary_voltage
        if not up_v:
            return None
        shift = self.phase_shift_deg

        def xform_v(p):
            return VoltagePhasor(p.magnitude / self.ratio, p.angle_degrees + shift)

        return wye_voltages(xform_v(up_v.a), xform_v(up_v.b), xform_v(up_v.c))

    @property
    def voltage(self):
        if self._evaluating:
            return None
        self._evaluating = True
        try:
            return self.secondary_voltage
        finally:
            self._evaluating = False

    @property
    def downstream_voltage(self):
        return self.voltage

    # ── Current ──────────────────────────────────────────────────────────────

    @property
    def primary_current(self):
        if self.upstream_device:
            if hasattr(self.upstream_device, "downstream_current"):
                return self.upstream_device.downstream_current
            return getattr(self.upstream_device, "current", None)
        return None

    @property
    def secondary_current(self):
        up_i = self.primary_current
        if not up_i:
            return None
        shift = self.phase_shift_deg

        def xform_i(p):
            return CurrentPhasor(p.magnitude * self.ratio, p.angle_degrees + shift)

        return wye_currents(xform_i(up_i.a), xform_i(up_i.b), xform_i(up_i.c))

    @property
    def current(self):
        if self._evaluating:
            return None
        self._evaluating = True
        try:
            return self.secondary_current
        finally:
            self._evaluating = False

    @property
    def downstream_current(self):
        return self.current

    # ── Summary ───────────────────────────────────────────────────────────────

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
