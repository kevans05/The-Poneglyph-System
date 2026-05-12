from .bus import Bus
import math
from ..voltage_phasor import VoltagePhasor
from ..current_phasor import CurrentPhasor
from ..wye_system import wye_currents, wye_voltages
from ..utilities.power_utilities import append_3phase_details


class VoltageRegulator(Bus):
    """
    A 3-phase Step Voltage Regulator.

    Typically has 32 steps (±16), each 0.625 %, for a ±10 % range.

    Automatic Voltage Regulation (AVR)
    -----------------------------------
    When avr_enabled=True, sim_step() compares the measured output voltage
    against nominal_kv and steps tap_pos ±1 each time the voltage remains
    outside the deadband for avr_delay_ms milliseconds of sim time.
    One tap change is allowed per delay period (integrating regulator model).
    """

    def __init__(
        self,
        name: str,
        nominal_kv: float,
        tap_pos: int = 0,
        step_percent: float = 0.625,
        max_steps: int = 16,
        avr_enabled: bool = False,
        avr_deadband_pct: float = 2.5,
        avr_delay_ms: float = 30000.0,
    ):
        super().__init__(name)
        self.nominal_kv = nominal_kv
        self.tap_pos = max(-max_steps, min(tap_pos, max_steps))
        self.step_percent = step_percent
        self.max_steps = max_steps
        self.avr_enabled = avr_enabled
        self.avr_deadband_pct = avr_deadband_pct
        self.avr_delay_ms = avr_delay_ms
        self._avr_hold_ms = 0.0   # time voltage has been outside deadband
        self._avr_prev_time = None

    # ------------------------------------------------------------------ ratio

    @property
    def ratio(self) -> float:
        return 1.0 / (1.0 + (self.tap_pos * self.step_percent / 100.0))

    # ------------------------------------------------------- power-flow graph

    def connect(self, downstream_device, **kwargs):
        if downstream_device not in self.connections:
            self.connections.append(downstream_device)
        downstream_device.upstream_device = self
        return downstream_device

    @property
    def connection_type(self) -> str:
        if self.upstream_device:
            return getattr(
                self.upstream_device,
                "downstream_connection_type",
                getattr(self.upstream_device, "connection_type", "wye"),
            )
        return "wye"

    @property
    def downstream_connection_type(self) -> str:
        return self.connection_type

    # --------------------------------------------------------- voltage / current

    @property
    def voltage(self):
        if "voltage" in self._cache:
            return self._cache["voltage"]
        if self._evaluating_v:
            return wye_voltages()
        self._evaluating_v = True
        try:
            up_v = None
            if self.upstream_device:
                up_v = getattr(
                    self.upstream_device,
                    "downstream_voltage",
                    getattr(self.upstream_device, "voltage", None),
                )
            if not up_v or not up_v.is_energized():
                return wye_voltages()
            r = self.ratio
            res = wye_voltages(
                VoltagePhasor(up_v.a.magnitude / r, up_v.a.angle_degrees),
                VoltagePhasor(up_v.b.magnitude / r, up_v.b.angle_degrees),
                VoltagePhasor(up_v.c.magnitude / r, up_v.c.angle_degrees),
            )
            self._cache["voltage"] = res
            return res
        finally:
            self._evaluating_v = False

    @property
    def downstream_voltage(self):
        return self.voltage

    @property
    def current(self):
        if "current" in self._cache:
            return self._cache["current"]
        if self._evaluating_i:
            return wye_currents()
        self._evaluating_i = True
        try:
            up_i = None
            if self.upstream_device:
                up_i = getattr(
                    self.upstream_device,
                    "downstream_current",
                    getattr(self.upstream_device, "current", None),
                )
            if not up_i or not up_i.is_energized():
                return wye_currents()
            r = self.ratio
            res = wye_currents(
                CurrentPhasor(up_i.a.magnitude * r, up_i.a.angle_degrees),
                CurrentPhasor(up_i.b.magnitude * r, up_i.b.angle_degrees),
                CurrentPhasor(up_i.c.magnitude * r, up_i.c.angle_degrees),
            )
            self._cache["current"] = res
            return res
        finally:
            self._evaluating_i = False

    @property
    def downstream_current(self):
        return self.current

    # --------------------------------------------------------- sim_step (AVR)

    def sim_step(self, sim_time_ms: float) -> list:
        events = super().sim_step(sim_time_ms)

        if self._avr_prev_time is None:
            self._avr_prev_time = sim_time_ms
            return events

        dt_ms = sim_time_ms - self._avr_prev_time
        self._avr_prev_time = sim_time_ms

        if not self.avr_enabled or dt_ms <= 0:
            return events

        v = self.voltage
        if not v or not v.is_energized():
            self._avr_hold_ms = 0.0
            return events

        v_ln_nom = self.nominal_kv * 1000.0 / math.sqrt(3.0)
        v_avg = (v.a.magnitude + v.b.magnitude + v.c.magnitude) / 3.0
        v_pu = v_avg / v_ln_nom if v_ln_nom > 0 else 1.0
        deadband = self.avr_deadband_pct / 100.0

        if abs(v_pu - 1.0) <= deadband:
            self._avr_hold_ms = 0.0
            return events

        self._avr_hold_ms += dt_ms
        if self._avr_hold_ms < self.avr_delay_ms:
            return events

        self._avr_hold_ms = 0.0
        if v_pu > 1.0 + deadband and self.tap_pos > -self.max_steps:
            self.tap_pos -= 1
            self._cache.clear()
        elif v_pu < 1.0 - deadband and self.tap_pos < self.max_steps:
            self.tap_pos += 1
            self._cache.clear()

        return events

    # --------------------------------------------------------- summary

    def get_summary_dict(self):
        boost_buck = "Boost" if self.tap_pos > 0 else "Buck" if self.tap_pos < 0 else "Neutral"
        regulation = self.tap_pos * self.step_percent
        is_delta = self.connection_type == "delta"

        stats = {
            "Type": "Voltage Regulator",
            "Nominal kV": self.nominal_kv,
            "Tap Position": f"{self.tap_pos:+d} ({boost_buck})",
            "Regulation": f"{regulation:+.3f}%",
            "Ratio": f"{1.0 / self.ratio:.4f}",
            "Connection": "Delta (Δ)" if is_delta else "Wye (Y)",
        }
        if self.avr_enabled:
            stats["AVR"] = f"ON  deadband={self.avr_deadband_pct}%  delay={self.avr_delay_ms/1000:.1f}s"

        v = self.voltage
        if not v or not v.is_energized():
            stats["Status"] = "DEAD (Disconnected)"

        return append_3phase_details(stats, v, self.current, is_delta=is_delta)
