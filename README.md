# Heading Sensor Calibration Dashboard

[![tests](https://github.com/mohamd764/Heading-Sensor-Calibration-Dashboard/actions/workflows/tests.yml/badge.svg)](https://github.com/mohamd764/Heading-Sensor-Calibration-Dashboard/actions/workflows/tests.yml)

An interactive Python / [Dash](https://dash.plotly.com/) application for **calibrating a vessel's
heading sensor (gyrocompass, GNSS compass or similar)** against an independent true heading
measured with a total station from shore.

A surveyor sets up on a known control point, backsights a second control point, and observes
prisms on the vessel's **Bow** and **Stem** while the sensor heading is recorded. The app reduces
those observations to grid coordinates, derives the vessel's **calculated true heading (C)**,
compares it with the **observed sensor heading (O)**, and reports **C − O** statistics. You can
export the result as a PDF report.

> All data in this repository is synthetic. See [Sample data](#sample-data).

## Features

- Explicit coordinate reference system: a WGS 84 UTM zone and hemisphere, or **any projected
  EPSG code** (NAD83 State Plane, NAD83 UTM, MGA and so on). A helper suggests the UTM zone from
  an approximate latitude and longitude.
- Rigorous grid convergence for any conformal projection, computed with PROJ via `pyproj`.
- Live grid bearing and convergence display, with warnings for implausible zone and coordinate
  combinations.
- 20-row Bow/Stem observation table, per-pair calculated heading, and C − O mean, sample standard
  deviation and range.
- One-click **PDF report** (US Letter, landscape).
- **Load sample data** button for an instant demo.
- The calculation core (`heading_calibration/`) is independent of the UI and fully unit-tested,
  including against published geodetic reference values.

## The math

Notation: station $S=(E_0,N_0)$, backsight $B=(E_B,N_B)$, horizontal directions read on the
instrument $r$, and horizontal distances $d$.

1. **Grid bearing to the backsight.**
   $\beta_{SB} = \operatorname{atan2}(E_B-E_0,\;N_B-N_0)$
2. **Orient each observation to grid.** For a target with reading $r_i$:
   $\theta_i = \beta_{SB} + (r_i - r_B)$
3. **Coordinates of the Bow and Stem prisms.**
   $E_i = E_0 + d_i\sin\theta_i,\quad N_i = N_0 + d_i\cos\theta_i$
4. **Grid heading of the centreline (Stem to Bow).**
   $H_{grid} = \operatorname{atan2}(E_{bow}-E_{stem},\;N_{bow}-N_{stem})$
5. **True heading.** $C = H_{grid} + \gamma$, where $\gamma$ is the grid convergence at the
   station.
6. **C − O.** $C - O$ wrapped to $[-180°, 180°)$. The app reports the mean, the sample
   standard deviation $(n-1)$ and the range over all Bow/Stem pairs.

### Grid convergence

$\gamma$ is the angle between grid north and true north. The sign convention used throughout is
**true azimuth = grid bearing + γ**. In the northern hemisphere, γ is positive east of the central
meridian.

The app computes γ numerically for the selected CRS. It converts the station to latitude and
longitude, projects two points a tiny step north and south along that meridian, and takes the grid
bearing of that "true north" vector. This works for Transverse Mercator (UTM), Lambert Conformal
Conic (most State Plane zones) and any other conformal projection, and it does not depend on PROJ's
own sign conventions. For UTM it agrees with the classic approximation
$\gamma \approx \arctan(\tan\Delta\lambda\,\sin\varphi)$ to better than 0.2″.

**Why the zone must be supplied.** A UTM easting only encodes the distance from the zone's central
meridian (false easting 500 000 m), not which zone the point is in. An earlier version derived the
zone as `int((easting // 1_000_000) % 60) + 1`. For every valid UTM easting (about 160 000 to
840 000 m) that yields zone 1, which is almost certainly the wrong zone. Pure UTM coordinates were
unaffected in practice: γ depends only on the offset from the central meridian and on latitude, and
both are the same whichever zone is assumed. The approach was silently and badly wrong for any
non-UTM grid, however. For NAD83 California zone 3 coordinates, for example, it gave about +13.5°
instead of −1.2°. It also showed no warning. The zone or EPSG code is now an explicit input.

### Assumptions

- Distances are horizontal. Reduce slope distances before entry.
- Each Bow row is paired with the Stem row immediately below it. Observe the pair as close together
  in time as possible.
- γ is evaluated at the instrument station. Over the few hundred metres to a vessel, the variation
  is negligible (well under 1″).
- Coordinates and distances must use the same linear unit. For a US survey foot State Plane CRS,
  enter distances in US survey feet.

## Quick start

Requires Python 3.12 or newer.

```bash
git clone https://github.com/mohamd764/Heading-Sensor-Calibration-Dashboard.git
cd Heading-Sensor-Calibration-Dashboard
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                                        # http://127.0.0.1:8050
```

Click **Load sample data**, then **Calculate**, then **Export to PDF**.

Set `DASH_DEBUG=1` to enable Dash's debug mode and hot reload. For deployment, serve the Flask
server with a WSGI server, for example `gunicorn app:server`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

The test suite includes:

- **Published reference values.** The Flinders Peak and Buninyong worked examples from the
  *Geocentric Datum of Australia Technical Manual* (ICSM). The tests reproduce the published MGA
  coordinates to 1 mm and the published grid convergence (+1°35′03.65″ and −1°47′19.36″) to
  0.01″.
- Sign convention, and zero convergence on the central meridian and on the equator.
- Agreement with the UTM series formula, and with the Lambert Conformal Conic convergence for a
  State Plane zone.
- A regression test documenting the old easting-to-zone formula.
- End-to-end reduction of synthetic Bow/Stem geometry for all headings, wrap-around at north, and
  handling of invalid or blank rows.
- The Dash callbacks, including PDF export and HTML escaping in the report.

CI runs on Python 3.12 and 3.13 through GitHub Actions.

## Sample data

`sample_data/sample_job.json` is **fully synthetic**. It is generated by
`scripts/make_sample_data.py` from a fixed random seed:

- a fictional job, client, vessel and staff ("Example Marine Co.", "MV Sample Vessel", "J. Doe"),
- round-number station coordinates in WGS 84 / UTM zone 15N, chosen only so that the grid
  convergence is clearly non-zero (about −1.29°),
- 10 Bow/Stem pairs simulated from a known sensor error of **C − O = +0.35°**, with 2″ direction,
  2 mm distance and 0.03° heading noise.

The app recovers a mean C − O of about +0.34°, with a standard deviation of about 0.02°.

## Project structure

```
app.py                         Dash UI and callbacks
heading_calibration/
    geodesy.py                 angles, DMS, CRS resolution, grid bearing, grid convergence
    calibration.py             observation reduction and C-O statistics (UI-independent)
    report.py                  HTML / PDF report
sample_data/sample_job.json    synthetic demo job
scripts/make_sample_data.py    generator for the demo job
tests/                         pytest suite
```

## License

No license has been chosen yet. Until one is added, all rights are reserved. The MIT License is
suggested for a portfolio project.

## Author

Mohamed Fouad, Data Analyst and geospatial Python developer.
