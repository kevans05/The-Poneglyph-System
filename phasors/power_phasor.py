import cmath
import math

from .utilities.formatter import SIPrefix


class PowerPhasor:
    """Represents complex power in polar and rectangular form"""

    def __init__(self, complex_power=0+0j):
        if not isinstance(complex_power, complex):
            raise TypeError("PowerPhasor requires a complex number")
        self.complex_power = complex_power

    @property
    def real(self):
        """Active (real) power in watts"""
        return self.complex_power.real

    @property
    def reactive(self):
        """Reactive power in vars"""
        return self.complex_power.imag

    @property
    def apparent(self):
        """Apparent power magnitude in VA"""
        return abs(self.complex_power)

    @property
    def angle_degrees(self):
        """Power factor angle in degrees"""
        return math.degrees(cmath.phase(self.complex_power))

    @property
    def power_factor(self):
        """Cosine of the power angle"""
        return math.cos(cmath.phase(self.complex_power))

    def to_polar(self):
        """Return polar form (magnitude, angle in degrees)"""
        mag, ang_rad = cmath.polar(self.complex_power)
        return mag, math.degrees(ang_rad)

    def re_reference(self, reference_angle_deg =0):
        """
        Return a new PowerPhasor with its angle shifted relative to a reference.
        Example: reference_angle_deg = 0 for absolute, or another phasor's angle.
        """
        mag, ang_deg = self.to_polar()
        new_angle = ang_deg - reference_angle_deg
        # Rebuild complex power with shifted angle
        shifted_complex = cmath.rect(mag, math.radians(new_angle))
        return PowerPhasor(shifted_complex)
        
    def __repr__(self):
        return (f"PowerPhasor(P={self.real:.2f} W, "
                f"Q={self.reactive:.2f} var, "
                f"|S|={self.apparent:.2f} VA ∠ {self.angle_degrees:.2f} deg)")

    def __add__(self, other):
        if not isinstance(other, PowerPhasor):
            raise TypeError("Can only add PowerPhasor to another PowerPhasor")
        return PowerPhasor(self.complex_power + other.complex_power)
        
    def __str__(self):
        p = SIPrefix.format_value(self.real, "W")
        q = SIPrefix.format_value(self.reactive, "var")
        s = SIPrefix.format_value(self.apparent, "VA")
        return f"P: {p:<15} Q: {q:<15} |S|: {s:<15} PF: {self.power_factor:.3f}"