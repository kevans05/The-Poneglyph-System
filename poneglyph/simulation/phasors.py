"""3-phase phasor utilities.

All angles in radians internally. Voltages in volts (line-to-neutral),
currents in amps. Complex numbers represent phasors: real=in-phase, imag=quadrature.
"""

import cmath
import math
from dataclasses import dataclass


# Phase offsets for balanced 3-phase (A leads, B lags 120°, C lags 240°)
PHASE_A = 0.0
PHASE_B = -2 * math.pi / 3
PHASE_C = 2 * math.pi / 3


def polar(magnitude: float, angle_deg: float) -> complex:
    """Create a phasor from magnitude and angle in degrees."""
    return cmath.rect(magnitude, math.radians(angle_deg))


def to_polar(phasor: complex) -> tuple[float, float]:
    """Return (magnitude, angle_degrees) for a phasor."""
    r, theta = cmath.polar(phasor)
    return r, math.degrees(theta)


def balanced_voltages(v_ln: float, angle_a_deg: float = 0.0) -> tuple[complex, complex, complex]:
    """Return (Va, Vb, Vc) for a balanced 3-phase source."""
    a0 = math.radians(angle_a_deg)
    Va = cmath.rect(v_ln, a0 + PHASE_A)
    Vb = cmath.rect(v_ln, a0 + PHASE_B)
    Vc = cmath.rect(v_ln, a0 + PHASE_C)
    return Va, Vb, Vc


@dataclass
class ThreePhaseQuantity:
    """A, B, C phasors for any 3-phase electrical quantity."""
    a: complex
    b: complex
    c: complex

    def magnitudes(self) -> tuple[float, float, float]:
        return abs(self.a), abs(self.b), abs(self.c)

    def angles_deg(self) -> tuple[float, float, float]:
        return (
            math.degrees(cmath.phase(self.a)),
            math.degrees(cmath.phase(self.b)),
            math.degrees(cmath.phase(self.c)),
        )

    def as_dict(self) -> dict:
        return {
            "A": {"mag": abs(self.a), "ang": math.degrees(cmath.phase(self.a))},
            "B": {"mag": abs(self.b), "ang": math.degrees(cmath.phase(self.b))},
            "C": {"mag": abs(self.c), "ang": math.degrees(cmath.phase(self.c))},
        }
