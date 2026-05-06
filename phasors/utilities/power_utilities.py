from phasors.utilities.formatter import SIPrefix
import math

def get_theta(power_factor: float, lead_lag: str) -> float:
    if not (0.0 <= power_factor <= 1.0): raise ValueError('Power factor must be between 0.0 and 1.0')
    theta_rad = math.acos(power_factor)
    theta_deg = math.degrees(theta_rad)
    lead_lag = lead_lag.strip().lower()
    if lead_lag == 'lag': return -theta_deg
    elif lead_lag == 'lead': return theta_deg
    else: raise ValueError("lead_lag parameter must be exactly 'lead' or 'lag'")

def calculate_current_angle(voltage_angle_deg: float, power_factor: float, lead_lag: str) -> float:
    theta_diff = get_theta(power_factor, lead_lag)
    return voltage_angle_deg + theta_diff
    
def print_device_summary(device_name: str, values_dict: dict, custom_units_map: dict = None):
    units_map = {
        'Active Power': 'W', 'Reactive Power': 'var', 'Apparent Power': 'VA',
        'Line Voltage (LL)': 'V', 'Phase Voltage (LN)': 'V', 'Current': 'A',
        '3-Phase Current': 'A',
        'Phase A Voltage (LN)': 'V', 'Phase B Voltage (LN)': 'V', 'Phase C Voltage (LN)': 'V',
        'Phase A V-Angle': 'deg', 'Phase B V-Angle': 'deg', 'Phase C V-Angle': 'deg',
        'Phase A Current': 'A', 'Phase B Current': 'A', 'Phase C Current': 'A',
        'Phase A I-Angle': 'deg', 'Phase B I-Angle': 'deg', 'Phase C I-Angle': 'deg',
        'Secondary Current': 'A', 'Sec Current Phase A': 'A', 'Sec Current Phase B': 'A', 'Sec Current Phase C': 'A',
        'Continuous Rating': 'A'
    }
    if custom_units_map: units_map.update(custom_units_map)
    print('\n' + '=' * 50)
    print(f'THREE-PHASE POWER SUMMARY AT {device_name.upper():^17}')
    print('=' * 50)
    print(f"{'PARAMETER':<30} | {'VALUE':>17}")
    print('-' * 50)
    for key, value in values_dict.items():
        if value == 'HEADER':
            print('-' * 50); print(f'{key:^50}'); print('-' * 50); continue
        if key in units_map:
            formatted_val = SIPrefix.format_value(value, units_map[key])
            print(f'{key:<30} | {formatted_val:>17}')
        elif isinstance(value, (int, float)): print(f'{key:<30} | {value:>17.3f}')
        else: print(f'{key:<30} | {str(value).upper():>17}')
    print('=' * 50 + '\n')
    
def _phase_pqs(v_mag: float, v_ang_deg: float, i_mag: float, i_ang_deg: float):
    """Single-phase complex power S = V · I*  (returns P [W], Q [var], |S| [VA])."""
    if v_mag is None or i_mag is None:
        return None
    s_mag = v_mag * i_mag
    if s_mag == 0:
        return (0.0, 0.0, 0.0)
    delta = math.radians(v_ang_deg - i_ang_deg)
    return (s_mag * math.cos(delta), s_mag * math.sin(delta), s_mag)


def append_3phase_details(stats_dict: dict, voltage_obj, current_obj, is_delta: bool = False):
    if not voltage_obj and not current_obj: return stats_dict

    if is_delta:
        # Delta: voltages are line-to-line (V_AB = V_A − V_B, etc); the
        # measurable currents are the LINE currents I_A, I_B, I_C flowing into
        # each terminal of the delta. The internal per-leg currents I_AB, I_BC,
        # I_CA are not directly measurable (any zero-sequence circulating
        # current is invisible from outside the delta). Under the standard
        # assumption that the circulating zero-sequence component is zero:
        #     I_AB = (I_A − I_B) / 3
        #     I_BC = (I_B − I_C) / 3
        #     I_CA = (I_C − I_A) / 3
        # Per-leg complex power is then  S_leg = V_LL · conj(I_leg). Summing
        # the three legs reproduces the same total 3-phase power you would get
        # from V_LN · conj(I_line) summed over A, B, C.
        leg_specs = [
            # (display label, V_from, V_to, line label, line attr, next line attr)
            ('A-B', 'a', 'b', 'A', 'a', 'b'),
            ('B-C', 'b', 'c', 'B', 'b', 'c'),
            ('C-A', 'c', 'a', 'C', 'c', 'a'),
        ]
        for ll_label, v_from, v_to, line_lbl, i_from_attr, i_to_attr in leg_specs:
            stats_dict[f'--- PHASE {ll_label} ---'] = 'HEADER'
            v_ll = None
            if voltage_obj:
                v_ll = getattr(voltage_obj, v_from) - getattr(voltage_obj, v_to)
                stats_dict[f'Phase {ll_label} Voltage'] = v_ll.magnitude
                stats_dict[f'Phase {ll_label} V-Angle'] = v_ll.angle_degrees
            i_leg = None
            if current_obj:
                # Line current at terminal A/B/C — keep original key names
                i_line = getattr(current_obj, i_from_attr)
                stats_dict[f'Phase {line_lbl} Current'] = i_line.magnitude
                stats_dict[f'Phase {line_lbl} I-Angle'] = i_line.angle_degrees
                # Computed per-leg current (no zero-sequence assumption)
                i_a = getattr(current_obj, i_from_attr)
                i_b = getattr(current_obj, i_to_attr)
                i_leg = (i_a - i_b) / 3.0
                stats_dict[f'Leg {ll_label} Current'] = i_leg.magnitude
                stats_dict[f'Leg {ll_label} I-Angle'] = i_leg.angle_degrees
            if v_ll is not None and i_leg is not None:
                pqs = _phase_pqs(v_ll.magnitude, v_ll.angle_degrees,
                                 i_leg.magnitude, i_leg.angle_degrees)
                if pqs is not None:
                    p, q, s = pqs
                    stats_dict[f'Phase {ll_label} Active Power']   = p
                    stats_dict[f'Phase {ll_label} Reactive Power'] = q
                    stats_dict[f'Phase {ll_label} Apparent Power'] = s
    else:
        for phase_label, attr in [('A', 'a'), ('B', 'b'), ('C', 'c')]:
            stats_dict[f'--- PHASE {phase_label} ---'] = 'HEADER'
            v_phasor = None
            i_phasor = None
            if voltage_obj:
                v_phasor = getattr(voltage_obj, attr)
                stats_dict[f'Phase {phase_label} Voltage (LN)'] = v_phasor.magnitude
                stats_dict[f'Phase {phase_label} V-Angle'] = v_phasor.angle_degrees
            if current_obj:
                i_phasor = getattr(current_obj, attr)
                stats_dict[f'Phase {phase_label} Current'] = i_phasor.magnitude
                stats_dict[f'Phase {phase_label} I-Angle'] = i_phasor.angle_degrees
            if v_phasor is not None and i_phasor is not None:
                pqs = _phase_pqs(v_phasor.magnitude, v_phasor.angle_degrees,
                                 i_phasor.magnitude, i_phasor.angle_degrees)
                if pqs is not None:
                    p, q, s = pqs
                    stats_dict[f'Phase {phase_label} Active Power']   = p
                    stats_dict[f'Phase {phase_label} Reactive Power'] = q
                    stats_dict[f'Phase {phase_label} Apparent Power'] = s
    return stats_dict