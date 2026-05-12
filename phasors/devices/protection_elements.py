"""
protection_elements.py — Pluggable protection function elements.

Each class models a single IED protection function (50, 51, 59, …).
New functions are added by subclassing ProtectionElement and calling
register_element() — no changes to the Relay class are required.

Interface
---------
ProtectionElement.step(i_sys, v_sys, dt_ms) → list[event_dict]
    Advance the element by dt_ms milliseconds.  Returns zero or more event
    dicts (RELAY_PICKUP / RELAY_DROPOUT).  device_id is NOT set here;
    Relay.sim_step fills it in after collecting events from all elements.

ProtectionElement.get_bit() → bool
    The logical bit exposed to relay equations (e.g. "51P1 OR 50P1").
    For 50/59 this is the instantaneous pickup state; for 51 it is True only
    once the IDMT accumulator has reached 1.0 (element operated).

ProtectionElement.get_state() → dict
    Key-value pairs for the device summary / detail panel.

ProtectionElement.copy_state_from(other)
    Transfer mutable simulation state to a freshly-built element of the
    same type.  Called by SimEngine.mutate() when the topology reloads.

Adding a new element type (example: 21-series distance)
--------------------------------------------------------
    from phasors.devices.protection_elements import ProtectionElement, register_element

    class Distance21Element(ProtectionElement):
        def step(self, i_sys, v_sys, dt_ms):  ...
        def get_state(self):  ...

    register_element('21', Distance21Element)

After that one call the element is auto-detected from any relay settings
dict that contains a key matching ^21[A-Z]?\\d+P$ (e.g. '21P1P').
"""

import re
import math
import cmath

# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class ProtectionElement:
    """Base class for a single IED protection / measurement function."""

    def __init__(self, bit_name: str, settings: dict):
        self.bit_name = bit_name
        self.settings = settings   # shared reference — mutations are visible immediately
        self.operated = False

    def step(self, i_sys, v_sys, dt_ms: float) -> list:
        """Advance element state by dt_ms ms.  Return list of event dicts."""
        return []

    def get_bit(self) -> bool:
        """Logical bit value for use in relay equations."""
        return self.operated

    def get_state(self) -> dict:
        """Display key-value pairs for the summary panel."""
        return {self.bit_name: "ASSERTED" if self.operated else "0"}

    def copy_state_from(self, other: "ProtectionElement"):
        """Copy mutable sim state from another element of the same type."""
        self.operated = other.operated

    def reset(self):
        """Reset all state to power-up initial values."""
        self.operated = False


# ---------------------------------------------------------------------------
# Built-in element types
# ---------------------------------------------------------------------------

def _phase_current(i_sys, bit_name: str) -> float:
    """Return the current magnitude appropriate for the element type.
    51N*/51G* use residual |Ia+Ib+Ic|; everything else uses max phase."""
    etype = bit_name[2] if len(bit_name) > 2 else "P"
    if etype in ("N", "G") and i_sys and i_sys.is_energized():
        return abs(i_sys.a.to_complex() + i_sys.b.to_complex() + i_sys.c.to_complex())
    if i_sys and i_sys.is_energized():
        return max(i_sys.a.magnitude, i_sys.b.magnitude, i_sys.c.magnitude)
    return 0.0


class OC50Element(ProtectionElement):
    """Instantaneous overcurrent (50-series).
    Bit asserts immediately when measured current ≥ pickup; drops immediately below."""

    def step(self, i_sys, v_sys, dt_ms: float) -> list:
        pickup = float(self.settings.get(f"{self.bit_name}P", 5.0))
        self.operated = _phase_current(i_sys, self.bit_name) >= pickup
        return []

    def get_state(self) -> dict:
        pickup = self.settings.get(f"{self.bit_name}P", "?")
        return {self.bit_name: f'{"ASSERTED" if self.operated else "0"} (P={pickup}A)'}


class OV59Element(ProtectionElement):
    """Overvoltage (59-series).
    Bit asserts immediately when max phase voltage ≥ pickup."""

    def step(self, i_sys, v_sys, dt_ms: float) -> list:
        pickup = float(self.settings.get(f"{self.bit_name}P", 120.0))
        V = 0.0
        if v_sys and v_sys.is_energized():
            V = max(v_sys.a.magnitude, v_sys.b.magnitude, v_sys.c.magnitude)
        self.operated = V >= pickup
        return []

    def get_state(self) -> dict:
        pickup = self.settings.get(f"{self.bit_name}P", "?")
        return {self.bit_name: f'{"ASSERTED" if self.operated else "0"} (P={pickup}V)'}


class IDMT51Element(ProtectionElement):
    """Inverse-time overcurrent (51-series) with an integrating accumulator.

    Each frame the accumulator advances by dt / t_op(I).  The element operates
    (bit → True) when the accumulator reaches 1.0.  Resets instantaneously when
    I drops to ≤ 90 % of pickup.

    Supported curves (setting key: {bit_name}CURVE, default IEC_SI)
    ───────────────────────────────────────────────────────────────
    IEC 60255-151        IEEE C37.112
    IEC_SI  IEC_VI       IEEE_MI  IEEE_VI
    IEC_EI  IEC_LTI      IEEE_EI
    """

    CURVES = {
        "IEC_SI":  lambda m, k: k * 0.14   / (m ** 0.02 - 1),
        "IEC_VI":  lambda m, k: k * 13.5   / (m - 1),
        "IEC_EI":  lambda m, k: k * 80.0   / (m ** 2 - 1),
        "IEC_LTI": lambda m, k: k * 120.0  / (m - 1),
        "IEEE_MI": lambda m, k: k * (0.0515 / (m ** 0.02 - 1) + 0.114),
        "IEEE_VI": lambda m, k: k * (19.61  / (m ** 2  - 1)   + 0.491),
        "IEEE_EI": lambda m, k: k * (28.2   / (m ** 2  - 1)   + 0.1217),
    }

    def __init__(self, bit_name: str, settings: dict):
        super().__init__(bit_name, settings)
        self.accumulator = 0.0

    @classmethod
    def compute_time(cls, curve: str, multiple: float, tms: float) -> float:
        """Operating time in seconds. Returns inf when multiple ≤ 1.0."""
        if multiple <= 1.0:
            return float("inf")
        fn = cls.CURVES.get(curve)
        return fn(multiple, tms) if fn else tms   # definite-time fallback

    def step(self, i_sys, v_sys, dt_ms: float) -> list:
        pickup = float(self.settings.get(f"{self.bit_name}P", 0.0))
        tms    = float(self.settings.get(f"{self.bit_name}TMS",
                       self.settings.get(f"{self.bit_name}TDS", 1.0)))
        curve  = self.settings.get(f"{self.bit_name}CURVE", "IEC_SI")

        I        = _phase_current(i_sys, self.bit_name)
        multiple = (I / pickup) if pickup > 0 else 0.0
        events   = []

        if multiple > 1.0:
            t_op_s = self.compute_time(curve, multiple, tms)
            if t_op_s not in (float("inf"), 0.0):
                self.accumulator = min(1.0, self.accumulator + dt_ms / (t_op_s * 1000.0))
            if self.accumulator >= 1.0 and not self.operated:
                self.operated = True
                events.append({"type": "RELAY_PICKUP", "delay": 0, "data": {
                    "label":    self.bit_name,
                    "multiple": round(multiple, 2),
                    "curve":    curve,
                    "t_op_s":   round(t_op_s, 3) if t_op_s != float("inf") else None,
                }})
        elif multiple <= 0.9:
            self.accumulator = 0.0
            if self.operated:
                self.operated = False
                events.append({"type": "RELAY_DROPOUT", "delay": 0, "data": {
                    "label": self.bit_name,
                }})

        return events

    def get_state(self) -> dict:
        pickup = self.settings.get(f"{self.bit_name}P", "?")
        tms    = self.settings.get(f"{self.bit_name}TMS",
                 self.settings.get(f"{self.bit_name}TDS", "?"))
        curve  = self.settings.get(f"{self.bit_name}CURVE", "IEC_SI")
        status = "OPERATED" if self.operated else f"{self.accumulator * 100:.0f}% charged"
        return {f"51 {self.bit_name}": f"{status} | P={pickup}A TMS={tms} {curve}"}

    def copy_state_from(self, other: ProtectionElement):
        super().copy_state_from(other)
        self.accumulator = getattr(other, "accumulator", 0.0)

    def reset(self):
        super().reset()
        self.accumulator = 0.0


class DIR67Element(ProtectionElement):
    """Directional overcurrent supervisor (67-series).

    Asserts when measured current ≥ pickup AND the current phasor is in the
    forward direction relative to the polarizing voltage.  Designed to
    supervise 50/51 elements in relay logic equations, e.g.:

        "TRIP": "67P1 AND 51P1"   ← directional IDMT
        "TRIP": "67P1 AND 50P1"   ← directional instantaneous

    Directional criterion
    ---------------------
    For each phase the operating torque is:

        T = Re( I_ph × (V_ph · e^(jMTA))* )

    where MTA (Maximum Torque Angle) is the angle by which V is rotated
    to align it with the expected fault current direction.  The element
    asserts when T > 0 for any phase carrying current ≥ pickup.

    MTA convention (IEC 60255-181)
    --------------------------------
    V_pol = V · e^(−j·MTA).  Maximum torque when I lags V by MTA degrees.
    Forward zone: I angle within ±90° of (angle(V) − MTA).

    Typical MTA values
    ------------------
    30–45°  transmission line (high X/R) forward-looking
    45–60°  distribution feeder / general OC
    0°      resistive fault / bus zone supervision

    Settings
    --------
    {bit_name}P      : float — minimum current pickup (A, default 0.5)
    {bit_name}MTA    : float — maximum torque angle (°, default 60)
    {bit_name}VT_MIN : float — minimum polarizing voltage; below this the
                               element blocks (V, default 5)
    """

    def step(self, i_sys, v_sys, dt_ms: float) -> list:
        pickup  = float(self.settings.get(f"{self.bit_name}P",      0.5))
        mta_deg = float(self.settings.get(f"{self.bit_name}MTA",    60.0))
        vt_min  = float(self.settings.get(f"{self.bit_name}VT_MIN", 5.0))

        if not (i_sys and i_sys.is_energized()) or not (v_sys and v_sys.is_energized()):
            self.operated = False
            return []

        mta_phasor = cmath.exp(-1j * math.radians(mta_deg))
        forward = False

        for ph in ("a", "b", "c"):
            i_ph = getattr(i_sys, ph).to_complex()
            v_ph = getattr(v_sys, ph).to_complex()

            if abs(i_ph) < pickup:
                continue
            if abs(v_ph) < vt_min:      # no polarizing voltage — block
                continue

            # T = Re( I × (V · e^(jMTA))* )
            # Small tolerance guards against floating-point artefacts at the
            # exact ±90° boundary (T should be 0 there, not ±epsilon).
            torque = (i_ph * (v_ph * mta_phasor).conjugate()).real
            if torque > 1e-9 * abs(i_ph) * abs(v_ph):
                forward = True
                break

        self.operated = forward
        return []

    def get_state(self) -> dict:
        pickup = self.settings.get(f"{self.bit_name}P",   "?")
        mta    = self.settings.get(f"{self.bit_name}MTA", 60)
        status = "FORWARD" if self.operated else "REVERSE/BLOCKED"
        return {self.bit_name: f"{status} (P={pickup}A MTA={mta}°)"}


# ---------------------------------------------------------------------------
# Registry and factory
# ---------------------------------------------------------------------------

# Maps IEC function-number prefix → element class.
# Keys are strings; the factory matches ^({prefix}[A-Z]?\d+)P$ against settings.
_ELEMENT_REGISTRY: dict = {}


def register_element(prefix: str, cls: type):
    """Register a ProtectionElement subclass for a function-number prefix.

    Example:
        register_element('21', Distance21Element)
    After this call, any relay settings dict containing e.g. '21P1P' will
    automatically instantiate a Distance21Element('21P1', settings).
    """
    _ELEMENT_REGISTRY[prefix] = cls


def build_elements_from_settings(settings: dict) -> list:
    """Inspect a relay settings dict and return one element per detected function.

    Detection rule: a key matching ^({prefix}[A-Z]?\\d+)P$ where prefix is a
    registered function-number prefix creates an element of the corresponding
    class with bit_name = key[:-1] (stripping the trailing 'P').
    """
    elements = []
    seen: set = set()
    for key in settings:
        for prefix, cls in _ELEMENT_REGISTRY.items():
            m = re.match(rf"^({re.escape(prefix)}[A-Z]?\d+)P$", key)
            if m:
                bit_name = m.group(1)
                if bit_name not in seen:
                    elements.append(cls(bit_name, settings))
                    seen.add(bit_name)
    return elements


# Register built-in element types
register_element("50", OC50Element)
register_element("51", IDMT51Element)
register_element("59", OV59Element)
register_element("67", DIR67Element)
