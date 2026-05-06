from ..utilities.power_utilities import append_3phase_details
from .bus import Bus


class SurgeArrester(Bus):
    """Surge arrester (lightning arrester) — overvoltage protection, shunt-connected to a bushing."""

    def __init__(self, name: str, kv_rating: float = 115.0, location: str = "", bushing: str = "H"):
        super().__init__(name)
        self.kv_rating = kv_rating
        self.location = location
        self.bushing = bushing

    def get_summary_dict(self) -> dict:
        stats = {
            "Type": "Surge Arrester",
            "Rated kV (MCOV)": self.kv_rating,
            "Location": f"{self.location} ({self.bushing})" if self.location else "—",
            "Status": "Normal Operation (High Impedance)",
        }
        return append_3phase_details(stats, self.voltage, self.current)


class SeriesCapacitor(Bus):
    """Series capacitor — in-line capacitive reactance compensation."""

    def __init__(self, name: str, mvar_rating: float = 50.0, impedance_ohm: float = 10.0):
        super().__init__(name)
        self.mvar_rating = mvar_rating
        self.impedance_ohm = impedance_ohm

    def get_summary_dict(self) -> dict:
        stats = {
            "Type": "Series Capacitor",
            "Rated MVAr": self.mvar_rating,
            "Reactance (Xc)": f"{self.impedance_ohm:.3f} Ω",
        }
        return append_3phase_details(stats, self.voltage, self.current)


class SeriesReactor(Bus):
    """Series reactor — in-line inductive reactance (fault current limiting, harmonic filtering)."""

    def __init__(self, name: str, mvar_rating: float = 10.0, impedance_ohm: float = 5.0):
        super().__init__(name)
        self.mvar_rating = mvar_rating
        self.impedance_ohm = impedance_ohm

    def get_summary_dict(self) -> dict:
        stats = {
            "Type": "Series Reactor",
            "Rated MVAr": self.mvar_rating,
            "Reactance (XL)": f"{self.impedance_ohm:.3f} Ω",
        }
        return append_3phase_details(stats, self.voltage, self.current)


class NeutralGroundingResistor(Bus):
    """Neutral grounding resistor — limits ground fault current, connected at transformer neutral."""

    def __init__(self, name: str, resistance_ohm: float = 400.0, kv_rating: float = 13.8):
        super().__init__(name)
        self.resistance_ohm = resistance_ohm
        self.kv_rating = kv_rating

    def get_summary_dict(self) -> dict:
        stats = {
            "Type": "Neutral Grounding Resistor",
            "Resistance": f"{self.resistance_ohm:.1f} Ω",
            "Rated kV": self.kv_rating,
            "Function": "Ground Fault Current Limiting",
        }
        return append_3phase_details(stats, self.voltage, self.current)


class LineTrap(Bus):
    """Line trap (wave trap) — series LC device blocking carrier frequencies on power lines."""

    def __init__(self, name: str, carrier_frequency_hz: float = 250.0):
        super().__init__(name)
        self.carrier_frequency_hz = carrier_frequency_hz

    def get_summary_dict(self) -> dict:
        stats = {
            "Type": "Line Trap (Wave Trap)",
            "Carrier Frequency": f"{self.carrier_frequency_hz:.0f} Hz",
            "Function": "Power Line Carrier Blocking",
        }
        return append_3phase_details(stats, self.voltage, self.current)
