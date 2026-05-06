import math

from phasors.current_phasor import CurrentPhasor
from phasors.devices.bus import Bus
from phasors.devices.passive import LineTrap, NeutralGroundingResistor, SeriesCapacitor, SeriesReactor, SurgeArrester
from phasors.devices.power_line import PowerLine
from phasors.devices.protection import CTTB, FTBlock, IsoBlock, Relay
from phasors.devices.sensors import CurrentTransformer, VoltageTransformer, DualWindingVT
from phasors.devices.source_load import Load, ShuntCapacitor, ShuntReactor, SVC, VoltageSource
from phasors.devices.switching import CircuitBreaker, Disconnect
from phasors.devices.transformers import PowerTransformer
from phasors.voltage_phasor import VoltagePhasor
from phasors.wye_system import wye_currents, wye_voltages


class DeviceFactory:
    @staticmethod
    def create_device(data):
        dtype = data["type"]
        did = data["id"]

        if dtype == "VoltageSource":
            v_ln = (data["nominal_voltage_kv"] * 1000) / math.sqrt(3)
            pf = data["pf"]
            s_total = data["nominal_power_mva"] * 1e6
            i_mag = s_total / (math.sqrt(3) * data["nominal_voltage_kv"] * 1000)
            theta = -math.degrees(math.acos(pf))
            ps = data.get("phase_shift_deg", 0.0)
            nom_v = wye_voltages(
                VoltagePhasor(v_ln, 0 + ps),
                VoltagePhasor(v_ln, 120 + ps),
                VoltagePhasor(v_ln, 240 + ps),
            )
            nom_i = wye_currents(
                CurrentPhasor(i_mag, theta + ps),
                CurrentPhasor(i_mag, theta + 120 + ps),
                CurrentPhasor(i_mag, theta + 240 + ps),
            )
            return VoltageSource(
                did,
                nominal_voltage=nom_v,
                nominal_current=nom_i,
                winding_type=data.get("winding_type", "Y"),
                phase_shift_deg=ps,
            )

        elif dtype == "Bus" or dtype == "Wire":
            return Bus(did)

        elif dtype == "PowerLine":
            return PowerLine(did)

        elif dtype == "CircuitBreaker":
            dev = CircuitBreaker(
                did,
                continuous_amps=data["continuous_amps"],
                interrupt_ka=data["interrupt_ka"],
            )
            dev.is_closed = data["status"] == "CLOSED"
            return dev

        elif dtype == "Disconnect":
            dev = Disconnect(did)
            dev.is_closed = data["status"] == "CLOSED"
            return dev

        elif dtype == "CurrentTransformer":
            tap_ratios_data = data.get("tap_ratios")
            if tap_ratios_data:
                tap_ratios = {k: float(v) for k, v in tap_ratios_data.items()}
                selected_tap = data.get("selected_tap", next(iter(tap_ratios)))
            else:
                ratio_str = data.get("ratio", "2000:5")
                r = ratio_str.split(":")
                tap_ratios = {ratio_str: float(r[0]) / float(r[1])}
                selected_tap = ratio_str
            return CurrentTransformer(
                did,
                data.get("location", ""),
                tap_ratios,
                selected_tap,
                bushing=data.get("bushing", "X"),
                polarity_facing=data.get("polarity_facing", "AWAY"),
                position=data.get("position", "inner"),
                polarity_normal=data.get("polarity_normal", True),
                phase_shift_deg=data.get("phase_shift_deg", 0.0),
                secondary_wiring=data.get("secondary_wiring", "Y"),
            )

        elif dtype == "VoltageTransformer":
            tap_ratios_data = data.get("tap_ratios")
            if tap_ratios_data:
                tap_ratios = {k: float(v) for k, v in tap_ratios_data.items()}
                selected_tap = data.get("selected_tap", next(iter(tap_ratios)))
            else:
                ratio_str = data.get("ratio", "2000:1")
                r = ratio_str.split(":")
                tap_ratios = {ratio_str: float(r[0]) / float(r[1])}
                selected_tap = ratio_str
            return VoltageTransformer(
                did,
                data.get("location", ""),
                tap_ratios,
                selected_tap,
                bushing=data.get("bushing", "X"),
                polarity_normal=data.get("polarity_normal", True),
                phase_shift_deg=data.get("phase_shift_deg", 0.0),
            )

        elif dtype == "DualWindingVT":
            tap_ratios_data = data.get("tap_ratios")
            if tap_ratios_data:
                tap_ratios = {k: float(v) for k, v in tap_ratios_data.items()}
                selected_tap = data.get("selected_tap", next(iter(tap_ratios)))
            else:
                ratio_str = data.get("ratio", "2000:1")
                r = ratio_str.split(":")
                tap_ratios = {ratio_str: float(r[0]) / float(r[1])}
                selected_tap = ratio_str
            ratio2_str = data.get("sec2_ratio", "2000:1")
            r2 = ratio2_str.split(":")
            rv2 = float(r2[0]) / float(r2[1])
            return DualWindingVT(
                did,
                data.get("location", ""),
                tap_ratios,
                selected_tap,
                rv2,
                bushing=data.get("bushing", "X"),
                polarity_normal=data.get("polarity_normal", True),
                phase_shift_deg=data.get("phase_shift_deg", 0.0),
            )

        elif dtype == "PowerTransformer":
            return PowerTransformer(
                did,
                pri_kv=data.get("pri_kv", 230),
                sec_kv=data.get("sec_kv", 115),
                h_winding=data.get("h_winding", "Y"),
                x_winding=data.get("x_winding", "D"),
                polarity_reversed=data.get("polarity_reversed", False),
                tap_configs=data.get("tap_configs"),
                selected_tap_index=data.get("selected_tap_index", 0),
            )

        elif dtype == "Load":
            l = Load(
                did, 
                load_va=data.get("load_mva", 0) * 1e6, 
                power_factor=data.get("pf", 1.0),
                is_balanced=data.get("is_balanced", True)
            )
            # Load phase data if present
            if "phase_va" in data:
                l.phase_va = data["phase_va"]
            if "phase_pf" in data:
                l.phase_pf = data["phase_pf"]
            return l

        elif dtype == "CTTB":
            return CTTB(did, mode=data.get("mode", "SUM"))

        elif dtype == "FTBlock":
            return FTBlock(did)

        elif dtype == "IsoBlock":
            return IsoBlock(did)

        elif dtype == "Relay":
            return Relay(did, function=data.get("function", "Differential"))

        elif dtype == "ShuntCapacitor":
            return ShuntCapacitor(
                did,
                mvar_rating=data.get("mvar_rating", 10.0),
                kv_rating=data.get("kv_rating", 115.0),
            )

        elif dtype == "ShuntReactor":
            return ShuntReactor(
                did,
                mvar_rating=data.get("mvar_rating", 10.0),
                kv_rating=data.get("kv_rating", 115.0),
            )

        elif dtype == "SurgeArrester":
            return SurgeArrester(
                did,
                kv_rating=data.get("kv_rating", 115.0),
                location=data.get("location", ""),
                bushing=data.get("bushing", "H"),
            )

        elif dtype == "SeriesCapacitor":
            return SeriesCapacitor(
                did,
                mvar_rating=data.get("mvar_rating", 50.0),
                impedance_ohm=data.get("impedance_ohm", 10.0),
            )

        elif dtype == "SeriesReactor":
            return SeriesReactor(
                did,
                mvar_rating=data.get("mvar_rating", 10.0),
                impedance_ohm=data.get("impedance_ohm", 5.0),
            )

        elif dtype == "NeutralGroundingResistor":
            return NeutralGroundingResistor(
                did,
                resistance_ohm=data.get("resistance_ohm", 400.0),
                kv_rating=data.get("kv_rating", 13.8),
            )

        elif dtype == "SVC":
            return SVC(
                did,
                mvar_min=data.get("mvar_min", -50.0),
                mvar_max=data.get("mvar_max", 50.0),
                mvar_setting=data.get("mvar_setting", 0.0),
                kv_rating=data.get("kv_rating", 115.0),
            )

        elif dtype == "LineTrap":
            return LineTrap(
                did,
                carrier_frequency_hz=data.get("carrier_frequency_hz", 250.0),
            )

        return None
