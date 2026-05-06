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
        # Delta has no neutral — voltages are line-to-line: A-B, B-C, C-A.
        # Line currents remain A, B, C (flow into each delta node).
        ll_pairs = [('A-B', 'a', 'b'), ('B-C', 'b', 'c'), ('C-A', 'c', 'a')]
        i_phases  = [('A', 'a'), ('B', 'b'), ('C', 'c')]
        for (ll_label, from_attr, to_attr), (i_label, i_attr) in zip(ll_pairs, i_phases):
            stats_dict[f'--- PHASE {ll_label} ---'] = 'HEADER'
            v_ll = None
            if voltage_obj:
                # V_AB = V_A − V_B  (VoltagePhasor supports __sub__)
                v_ll = getattr(voltage_obj, from_attr) - getattr(voltage_obj, to_attr)
                stats_dict[f'Phase {ll_label} Voltage'] = v_ll.magnitude
                stats_dict[f'Phase {ll_label} V-Angle'] = v_ll.angle_degrees
            i_phasor = None
            if current_obj:
                i_phasor = getattr(current_obj, i_attr)
                stats_dict[f'Phase {i_label} Current'] = i_phasor.magnitude
                stats_dict[f'Phase {i_label} I-Angle'] = i_phasor.angle_degrees
            # Reference single-phase S = V_LL · I_line* — informative only,
            # not a textbook delta per-leg power. Keys are tagged "(LL·I)".
            if v_ll is not None and i_phasor is not None:
                pqs = _phase_pqs(v_ll.magnitude, v_ll.angle_degrees,
                                 i_phasor.magnitude, i_phasor.angle_degrees)
                if pqs is not None:
                    p, q, s = pqs
                    stats_dict[f'Phase {i_label} Active Power (LL·I)']   = p
                    stats_dict[f'Phase {i_label} Reactive Power (LL·I)'] = q
                    stats_dict[f'Phase {i_label} Apparent Power (LL·I)'] = s
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