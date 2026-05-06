from .voltage_phasor import VoltagePhasor
from .current_phasor import CurrentPhasor
from .power_phasor import PowerPhasor

def voltage_current_multiplier(v, i):
    if isinstance(v, VoltagePhasor) and isinstance(i, CurrentPhasor):
        return PowerPhasor(v.to_complex() * i.to_complex().conjugate())
    raise TypeError("Multiplication requires VoltagePhasor and CurrentPhasor")