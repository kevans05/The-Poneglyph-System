"""Compare model-predicted values against field readings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from poneglyph.metering.measurement import MeasurementPoint, PhaseReading


@dataclass
class PhaseDeviation:
    phase: str
    predicted_mag: float
    actual_mag: float
    predicted_ang: float
    actual_ang: float

    @property
    def magnitude_error_pct(self) -> float:
        if self.predicted_mag == 0:
            return float("inf")
        return abs(self.actual_mag - self.predicted_mag) / self.predicted_mag * 100.0

    @property
    def angle_error_deg(self) -> float:
        err = self.actual_ang - self.predicted_ang
        # Wrap to [-180, 180]
        return (err + 180) % 360 - 180

    @property
    def pass_fail(self) -> str:
        """Simple pass/fail: within 5% magnitude and 5° angle."""
        return "PASS" if self.magnitude_error_pct <= 5.0 and abs(self.angle_error_deg) <= 5.0 else "FAIL"


@dataclass
class PointComparison:
    point_id: str
    point_name: str
    deviations: list[PhaseDeviation]

    @property
    def overall(self) -> str:
        return "PASS" if all(d.pass_fail == "PASS" for d in self.deviations) else "FAIL"


def compare_point(point: MeasurementPoint) -> Optional[PointComparison]:
    """Return a comparison for the latest reading vs predicted, or None if no data."""
    reading = point.latest_reading
    if reading is None:
        return None

    pairs = [
        ("A", point.predicted_a, reading.phase_a),
        ("B", point.predicted_b, reading.phase_b),
        ("C", point.predicted_c, reading.phase_c),
    ]
    deviations = []
    for phase, predicted, actual in pairs:
        if predicted is None or actual is None:
            continue
        deviations.append(PhaseDeviation(
            phase=phase,
            predicted_mag=predicted.magnitude,
            actual_mag=actual.magnitude,
            predicted_ang=predicted.angle_deg,
            actual_ang=actual.angle_deg,
        ))

    return PointComparison(point_id=point.id, point_name=point.name, deviations=deviations)
