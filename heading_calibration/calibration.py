"""Heading calibration: reduce total-station observations to C-O statistics.

Workflow
--------
1. Grid bearing station -> backsight comes from their coordinates.
2. Each Bow/Stem direction is oriented to grid:
   ``plane bearing = grid bearing + (direction - backsight direction)``.
3. Bow/Stem grid coordinates: ``E = E0 + d sin(b)``, ``N = N0 + d cos(b)``.
4. Grid heading of the vessel centreline: ``atan2(E_bow - E_stem, N_bow - N_stem)``.
5. Calculated true heading = grid heading + grid convergence.
6. C - O = calculated true heading - observed (sensor) heading, wrapped to +/-180.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .geodesy import GridValues, decimal_to_dms, dms_to_decimal, normalize_0_360, normalize_angle

RESULT_COLUMNS = [
    "UTC Time",
    "Observation Point",
    "Plane Bearing (DMS)",
    "Obs Dist (m)",
    "Calc Easting",
    "Calc Northing",
    "Obs (O) True Heading (°)",
    "Calc (C) True Heading (°)",
    "C - O (°)",
]


def _to_float(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


@dataclass
class ReducedPoint:
    index: int
    utc_time: str
    point: str
    direction: float | None
    distance: float | None
    observed_heading: float | None
    plane_bearing: float | None = None
    easting: float | None = None
    northing: float | None = None

    @property
    def failed(self):
        return self.plane_bearing is None


@dataclass
class HeadingComparison:
    bow_index: int
    utc_time: str
    calculated: float
    observed: float | None

    @property
    def c_minus_o(self):
        if self.observed is None:
            return None
        return normalize_angle(self.calculated - self.observed)


@dataclass
class CalibrationResult:
    points: list[ReducedPoint]
    comparisons: list[HeadingComparison]
    total_rows: int
    successful_rows: int
    failed_rows: int
    warnings: list[str] = field(default_factory=list)

    @property
    def c_minus_o(self):
        return [c.c_minus_o for c in self.comparisons if c.c_minus_o is not None]

    @property
    def stats(self):
        values = np.asarray(self.c_minus_o, dtype=float)
        n = values.size
        return {
            "n": int(n),
            "mean": float(values.mean()) if n else None,
            # Sample standard deviation (n - 1): the C-O set is a sample of the sensor's error.
            "std": float(values.std(ddof=1)) if n > 1 else None,
            "min": float(values.min()) if n else None,
            "max": float(values.max()) if n else None,
        }

    def table_rows(self):
        """Rows keyed by RESULT_COLUMNS, formatted for display/reporting."""
        by_bow = {c.bow_index: c for c in self.comparisons}
        rows = []
        for p in self.points:
            comp = by_bow.get(p.index)
            show_obs = p.point.lower() == "bow" and p.observed_heading is not None
            rows.append({
                "UTC Time": p.utc_time,
                "Observation Point": p.point,
                "Plane Bearing (DMS)": decimal_to_dms(p.plane_bearing),
                "Obs Dist (m)": f"{p.distance:.3f}" if p.distance is not None and not p.failed else "N/A",
                "Calc Easting": f"{p.easting:.3f}" if p.easting is not None else "N/A",
                "Calc Northing": f"{p.northing:.3f}" if p.northing is not None else "N/A",
                "Obs (O) True Heading (°)": f"{p.observed_heading:.2f}" if show_obs else "N/A",
                "Calc (C) True Heading (°)": f"{comp.calculated:.2f}" if comp else "N/A",
                "C - O (°)": f"{comp.c_minus_o:.2f}" if comp and comp.c_minus_o is not None else "N/A",
            })
        return rows


def reduce_observations(rows, station_e, station_n, backsight_direction, grid: GridValues):
    """Reduce gyro table rows (dicts as produced by the Dash DataTable).

    Rows alternate Bow/Stem; a Bow row is paired with the Stem row that
    immediately follows it.
    """
    points = []
    total = successful = failed = 0

    for i, row in enumerate(rows or []):
        utc_time = str(row.get("utc_time") or "").strip()
        point = str(row.get("obs_point") or "").strip()
        deg, mn, sec = (_to_float(row.get(k)) for k in ("direction_deg", "direction_min", "direction_sec"))
        distance = _to_float(row.get("obs_distance"))
        observed = _to_float(row.get("obs_true_heading"))

        if not utc_time and deg is None and mn is None and sec is None and distance is None:
            continue

        total += 1
        direction = dms_to_decimal(deg, mn, sec)
        rp = ReducedPoint(i, utc_time, point, direction, distance, observed)
        if direction is None or distance is None or distance <= 0:
            failed += 1
        else:
            rp.plane_bearing = normalize_0_360(grid.bearing + (direction - backsight_direction))
            b = math.radians(rp.plane_bearing)
            rp.easting = station_e + distance * math.sin(b)
            rp.northing = station_n + distance * math.cos(b)
            successful += 1
        points.append(rp)

    by_index = {p.index: p for p in points}
    comparisons = []
    for p in points:
        if p.point.lower() != "bow" or p.failed:
            continue
        stem = by_index.get(p.index + 1)
        if stem is None or stem.point.lower() != "stem" or stem.failed:
            continue
        grid_heading = math.degrees(math.atan2(p.easting - stem.easting, p.northing - stem.northing))
        calculated = normalize_0_360(grid_heading + grid.convergence)
        comparisons.append(HeadingComparison(p.index, p.utc_time, calculated, p.observed_heading))

    return CalibrationResult(points, comparisons, total, successful, failed, list(grid.warnings))
