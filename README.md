# The Poneglyph System v2
### Substation Load Test Platform

A desktop application for electrical substation protection relay load testing.  
Built with Python + Tkinter. No browser or server required.

---

## Purpose

When commissioning protection relays on high-voltage equipment, engineers need to:

1. **Predict** what a power meter should read at every CT and VT point in the substation, based on the network topology and current loading.
2. **Record** actual meter readings from the field against named test points tied to engineering drawings.
3. **Compare** predicted vs actual — flag deviations and produce a structured field report.

---

## Architecture

```
poneglyph/
├── simulation/
│   ├── network.py              # Bus/branch topology model
│   ├── phasors.py              # 3-phase phasor utilities
│   ├── powerflow.py            # Newton-Raphson AC power flow solver
│   └── devices/
│       ├── transformer.py      # Two-winding power transformer
│       └── instrument_transformer.py  # CT and VT models
├── metering/
│   ├── measurement.py          # Measurement points and field readings
│   └── comparison.py          # Predicted vs actual deviation analysis
├── ui/
│   ├── main_window.py          # Root Tkinter window
│   └── (panels TBD)
├── data/
│   └── project.py              # JSON project save/load
└── app.py                      # App wiring
main.py                         # Entry point
```

---

## Getting Started

```bash
pip install -r requirements.txt
python main.py
```

Python 3.10+ required. Tkinter ships with the standard library.  
`numpy` and `scipy` are used by the power flow solver.

---

## Simulation Model

The AC power flow uses a **Newton-Raphson / Gauss-Seidel** solver on a per-unit admittance matrix (Y-bus). The model supports:

- Slack bus (infinite source, fixed voltage and angle)
- PQ buses (fixed active and reactive load/injection)
- Series branches with R + jX impedance (lines, transformer leakage)
- Open/closed breakers as branch connectivity
- CT secondary currents derived from solved branch currents
- VT secondary voltages derived from solved bus voltages

Full 3-phase quantities are recovered from the positive-sequence solution by applying balanced ±120° phase offsets.
