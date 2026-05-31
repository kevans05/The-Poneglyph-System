"""Vivre Card — utility functions: variance calc, forcing-neutral check, differential verification."""
from __future__ import annotations
import math
from .sea_chart import MeasurementPoint, VectorGroup


def check_forcing_neutral(a_point: MeasurementPoint, n_point: MeasurementPoint) -> dict:
    """
    Forcing-neutral test: B & C are shorted/isolated.
    A-phase and Neutral should be equal magnitude, 180° out of phase.
    Returns {"mag_ok": bool, "ang_ok": bool, "mag_diff": float, "ang_diff": float}
    """
    mag_diff = abs(a_point.meas_magnitude - n_point.meas_magnitude)
    raw_diff = (n_point.meas_angle - a_point.meas_angle) % 360
    ang_diff = raw_diff if raw_diff <= 180 else raw_diff - 360
    return {
        "mag_ok": mag_diff <= a_point.meas_magnitude * 0.05,
        "ang_ok": abs(abs(ang_diff) - 180) <= 5.0,
        "mag_diff": round(mag_diff, 4),
        "ang_diff": round(ang_diff, 2),
    }


def differential_deviation(points: list[MeasurementPoint]) -> float:
    """
    Differential test: sum of all CTTB currents into relay differential should be ~0.
    Returns the residual magnitude.
    """
    def to_rect(m, a):
        return (m * math.cos(math.radians(a)), m * math.sin(math.radians(a)))
    rx, ry = 0.0, 0.0
    for p in points:
        x, y = to_rect(p.meas_magnitude, p.meas_angle)
        rx += x
        ry += y
    return round(math.hypot(rx, ry), 4)
