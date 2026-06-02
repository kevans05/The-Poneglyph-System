"""Sea Chart — data models for the P&C Load Test module."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import math


@dataclass
class MeasurementPoint:
    """One measured quantity at one test point."""
    device_id: str          # e.g. "CT-1"
    device_name: str
    device_type: str        # "ct" | "vt" | "cttb" | "testblock" | "relay"
    phase: str = ""         # "A"|"B"|"C"|"N"|"AB"|"BC"|"CA"
    connection: str = "Wye" # mirrors CT secondary_config
    channel: int = 1        # 1 = reference, 2 = lagging
    # Predicted (from SLD model)
    pred_magnitude: float = 0.0
    pred_angle: float = 0.0     # degrees, 0–360 convention
    # Measured (user entry)
    meas_magnitude: float = 0.0
    meas_angle: float = 0.0

    # Computed
    @property
    def magnitude_delta(self) -> float:
        return round(self.meas_magnitude - self.pred_magnitude, 4)

    @property
    def angle_delta(self) -> float:
        d = (self.meas_angle - self.pred_angle) % 360
        return round(d if d <= 180 else d - 360, 2)

    @property
    def magnitude_pct_err(self) -> Optional[float]:
        if self.pred_magnitude == 0:
            return None
        return round(abs(self.magnitude_delta) / self.pred_magnitude * 100, 2)

    @property
    def flagged(self) -> bool:
        """True if error exceeds 5% magnitude or 5° angle."""
        pct = self.magnitude_pct_err
        return (pct is not None and pct > 5.0) or abs(self.angle_delta) > 5.0


@dataclass
class VectorGroup:
    """3-phase vector set for vectorial addition (3I0 / V0 calculation)."""
    a_mag: float = 0.0
    a_ang: float = 0.0
    b_mag: float = 0.0
    b_ang: float = 0.0
    c_mag: float = 0.0
    c_ang: float = 0.0
    n_mag: float = 0.0
    n_ang: float = 0.0   # measured neutral

    def calculated_neutral(self) -> tuple[float, float]:
        """Returns (magnitude, angle_deg) of vectorial sum A+B+C."""
        def to_rect(m, a):
            return (m * math.cos(math.radians(a)), m * math.sin(math.radians(a)))
        ax, ay = to_rect(self.a_mag, self.a_ang)
        bx, by = to_rect(self.b_mag, self.b_ang)
        cx, cy = to_rect(self.c_mag, self.c_ang)
        rx, ry = ax + bx + cx, ay + by + cy
        mag = round(math.hypot(rx, ry), 4)
        ang = round(math.degrees(math.atan2(ry, rx)) % 360, 1)
        return mag, ang


@dataclass
class ForcedNeutralResult:
    """Recorded forced-neutral test for one device."""
    device_id: str
    device_name: str
    shorted_phases: list            # e.g. ["B", "C"]
    ref_phase: str = "A"            # phase left energized as reference
    ref_mag: float = 0.0
    ref_ang: float = 0.0
    n_mag: float = 0.0
    n_ang: float = 0.0
    passed: bool = False
    notes: str = ""


@dataclass
class LoadTestRecord:
    """A complete saved load test session."""
    id: str                             # UUID
    project_name: str
    wo_number: str = ""
    technologist: str = ""
    timestamp: str = ""                 # ISO datetime
    protection_blocked: bool = False
    blocking_note: str = ""             # who was contacted, SIO/FVO reference
    points: list = field(default_factory=list)   # list of MeasurementPoint dicts
    vector_groups: list = field(default_factory=list)  # list of VectorGroup dicts
    forced_neutral_results: list = field(default_factory=list)
    # Voltage reference
    voltage_ref_id: str = ""
    voltage_ref_name: str = ""
    voltage_ref_mag: float = 0.0
    voltage_ref_ang: float = 0.0
    meter_ch2_lags_ch1: bool = False
    drawings: list = field(default_factory=list) # list of drawing name strings
    notes: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()
