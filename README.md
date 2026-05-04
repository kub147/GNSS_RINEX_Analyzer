# 🛰️ GNSS RINEX Analyzer

A web-based tool for analyzing GNSS RINEX observation and navigation files — generating plots, computing statistics, and performing Single Point Positioning (SPP).

## Features

- **File Support**: RINEX 2/3/4 observation (`.obs`, `.rnx`, `.26o`) and navigation files (`.nav`, `.26n`, `.26g`, `.26l`, `.26f`, `_MN.rnx`), plus SP3 precise ephemeris
- **Smart Upload**: Content-based file validation — upload to the correct slot automatically detected
- **Session Pairing**: Automatically verifies that Observation and Navigation files belong to the same measurement session
- **Plots**: Satellite visibility, skyplot with satellite tracks, DOP/NSat (GDOP/PDOP/HDOP/VDOP), SNR over time, SNR vs elevation, SNR/MP/EL
- **SPP Positioning**: Single Point Positioning using GPS-only broadcast ephemeris, with quality filtering and failure tracking
- **Interactive Map**: Leaflet-powered map with satellite/aerial/street layers, SPP trajectory visualization, and KML export for Google Earth
- **GNSS Systems**: GPS, GLONASS, Galileo, BeiDou, QZSS, SBAS — each with correct observable labels per system
- **Dark Mode**: Toggle between light and dark themes
- **Statistics**: Session duration, satellite counts per system, SNR distribution, DOP values, frequency bands, Galileo SNR analysis
- **Cross-File Validation**: Checks date consistency and system coverage between OBS, NAV, and SP3 files

## Quick Start (Local)

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python3 gnss_app.py
```

Open **http://localhost:8080** in your browser.

1. Upload a RINEX **Observation** file (required)
2. (Optional) Upload a matching **Navigation** file to unlock SPP positioning, DOP analysis, and skyplot
3. (Optional) Upload an **SP3** file for precise vs broadcast comparison
4. Click **Analyze** and explore the results

## Requirements

- Python 3.10+
- Flask
- NumPy
- Matplotlib (Agg backend — works headless)
- A modern web browser

## File Format Support

| Type | Extensions | Description |
|------|-----------|-------------|
| Observation | `.obs`, `.rnx`, `.26o`, `.27o` | Pseudorange, carrier phase, Doppler, SNR |
| Navigation | `.nav`, `.rnx`, `.26n`, `.26g`, `.26l`, `.26f`, `_MN.rnx` | Broadcast ephemeris (Keplerian + GLONASS state vector) |
| Precise | `.sp3` | IGS precise orbits |
| Archive | `.zip` | Auto-extracted |
