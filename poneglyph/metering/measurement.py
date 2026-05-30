"""Measurement point model.

A MeasurementPoint links a CT or VT to a named test location.
It stores both the model-predicted value and the field-recorded value
so they can be compared side-by-side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PhaseReading:
    """One phase of a field meter reading."""
    magnitude: float
    angle_deg: float
    phase: str  # "A", "B", or "C"


@dataclass
class MeterReading:
    """Raw reading from a field power meter (one measurement point, one snapshot)."""
    timestamp: datetime
    technician: str
    phase_a: Optional[PhaseReading] = None
    phase_b: Optional[PhaseReading] = None
    phase_c: Optional[PhaseReading] = None
    notes: str = ""


@dataclass
class MeasurementPoint:
    """A named test point in the network with predicted and actual readings."""
    id: str
    name: str
    drawing_ref: str        # Engineering drawing reference (e.g. "DWG-101 Sheet 3")
    quantity: str           # "current" or "voltage"
    instrument_id: str      # CT or VT id this point reads from

    # Model-predicted values (set after power flow solve)
    predicted_a: Optional[PhaseReading] = None
    predicted_b: Optional[PhaseReading] = None
    predicted_c: Optional[PhaseReading] = None

    # Field readings (appended as the job progresses)
    readings: list[MeterReading] = field(default_factory=list)

    def add_reading(self, reading: MeterReading) -> None:
        self.readings.append(reading)

    @property
    def latest_reading(self) -> Optional[MeterReading]:
        return self.readings[-1] if self.readings else None
