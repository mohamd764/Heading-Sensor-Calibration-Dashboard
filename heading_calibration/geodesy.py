"""Angle helpers, CRS resolution, grid bearing and grid (meridian) convergence."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

HEMISPHERES = ("North", "South")


# ------------------------------------------------------------------ angles


def dms_to_decimal(degrees, minutes, seconds):
    """Convert a positive D/M/S direction to decimal degrees, or None if invalid."""
    if None in (degrees, minutes, seconds):
        return None
    try:
        degrees, minutes, seconds = float(degrees), float(minutes), float(seconds)
    except (TypeError, ValueError):
        return None
    if not (0 <= degrees <= 360 and 0 <= minutes < 60 and 0 <= seconds < 60):
        return None
    return degrees + minutes / 60 + seconds / 3600


def decimal_to_dms(decimal_degrees, seconds_decimals=2):
    """Format decimal degrees as ``DDD° MM' SS.SS''`` (signed for negative angles)."""
    if decimal_degrees is None or not math.isfinite(decimal_degrees):
        return "N/A"
    sign = "-" if decimal_degrees < 0 else ""
    total_seconds = round(abs(decimal_degrees) * 3600, seconds_decimals)
    deg, rem = divmod(total_seconds, 3600)
    mn, sc = divmod(rem, 60)
    width = 3 + seconds_decimals if seconds_decimals else 2
    return f"{sign}{int(deg):03d}° {int(mn):02d}' {sc:0{width}.{seconds_decimals}f}''"


def normalize_angle(angle):
    """Wrap an angle to [-180, 180)."""
    return (angle + 180.0) % 360.0 - 180.0


def normalize_0_360(angle):
    """Wrap an angle to [0, 360)."""
    return angle % 360.0


def grid_bearing(e1, n1, e2, n2):
    """Grid bearing (degrees, 0-360) from point 1 to point 2 in a projected CRS."""
    return normalize_0_360(math.degrees(math.atan2(e2 - e1, n2 - n1)))


# ------------------------------------------------------------------ CRS


def utm_zone_from_lonlat(lon, lat):
    """Return ``(zone, hemisphere)`` for a WGS84 longitude/latitude.

    Includes the standard Norway (32V) and Svalbard (31X-37X) exceptions.
    """
    if not (-180 <= lon <= 180 and -80 <= lat <= 84):
        raise ValueError("Longitude must be in [-180, 180] and latitude in [-80, 84] for UTM.")
    zone = int((lon + 180) // 6) + 1
    if zone == 61:
        zone = 60
    if 56 <= lat < 64 and 3 <= lon < 12:
        zone = 32
    if 72 <= lat <= 84:
        if 0 <= lon < 9:
            zone = 31
        elif 9 <= lon < 21:
            zone = 33
        elif 21 <= lon < 33:
            zone = 35
        elif 33 <= lon < 42:
            zone = 37
    return zone, ("North" if lat >= 0 else "South")


def utm_epsg(zone, hemisphere):
    """EPSG code of WGS 84 / UTM for a zone (1-60) and hemisphere."""
    try:
        zone = int(zone)
    except (TypeError, ValueError):
        raise ValueError("UTM zone must be an integer between 1 and 60.") from None
    if not 1 <= zone <= 60:
        raise ValueError("UTM zone must be an integer between 1 and 60.")
    if hemisphere not in HEMISPHERES:
        raise ValueError("Hemisphere must be 'North' or 'South'.")
    return (32600 if hemisphere == "North" else 32700) + zone


def utm_zone_mismatch(crs, approx_lon, approx_lat):
    """Warning text if a UTM CRS disagrees with an approximate WGS84 position, else None.

    A UTM easting/northing looks identical in every zone, so an independent
    approximate position is the only way to validate the zone choice.
    """
    if not crs.utm_zone or approx_lon is None or approx_lat is None:
        return None
    try:
        zone, hemisphere = utm_zone_from_lonlat(float(approx_lon), float(approx_lat))
    except (TypeError, ValueError):
        return None
    selected = crs.utm_zone
    expected = f"{zone}{'N' if hemisphere == 'North' else 'S'}"
    if selected != expected:
        return f"Approximate position is in UTM zone {expected}, but zone {selected} is selected."
    return None


def resolve_projected_crs(zone=None, hemisphere=None, epsg=None):
    """Build the projected CRS of the survey coordinates.

    An explicit EPSG code takes precedence (e.g. 26910 NAD83 / UTM 10N,
    2227 NAD83 / California zone 3 ftUS, 28355 GDA94 / MGA 55); otherwise a
    WGS 84 / UTM CRS is built from ``zone`` and ``hemisphere``.
    """
    if epsg not in (None, ""):
        try:
            crs = CRS.from_epsg(int(epsg))
        except (CRSError, TypeError, ValueError):
            raise ValueError(f"EPSG:{epsg} is not a known coordinate reference system.") from None
    else:
        crs = CRS.from_epsg(utm_epsg(zone, hemisphere))
    if not crs.is_projected:
        raise ValueError(f"{crs.name} is not a projected CRS; grid coordinates are required.")
    return crs


# ------------------------------------------------------------------ convergence


@dataclass
class GridValues:
    bearing: float
    convergence: float
    lon: float
    lat: float
    crs_name: str
    warnings: list[str] = field(default_factory=list)

    @property
    def bearing_dms(self):
        return decimal_to_dms(self.bearing)

    @property
    def convergence_dms(self):
        return decimal_to_dms(self.convergence)


def _transformers(crs):
    geographic = crs.geodetic_crs
    to_geo = Transformer.from_crs(crs, geographic, always_xy=True)
    to_grid = Transformer.from_crs(geographic, crs, always_xy=True)
    return to_geo, to_grid


def grid_convergence(crs, easting, northing, step_deg=1e-6):
    """Grid convergence (degrees) at a projected point.

    Sign convention: ``true azimuth = grid bearing + convergence``. In the
    northern hemisphere convergence is positive east of the central meridian.

    Computed numerically as the grid bearing of true north (a central
    difference along the meridian through the point), so it is valid for any
    conformal projected CRS and independent of PROJ's sign conventions.
    """
    to_geo, to_grid = _transformers(crs)
    lon, lat = to_geo.transform(easting, northing)
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise ValueError("Coordinates could not be converted to latitude/longitude in this CRS.")
    e_s, n_s = to_grid.transform(lon, lat - step_deg)
    e_n, n_n = to_grid.transform(lon, lat + step_deg)
    return -math.degrees(math.atan2(e_n - e_s, n_n - n_s))


def calculate_grid_values(e1, n1, e2, n2, crs):
    """Grid bearing station->backsight and grid convergence at the station."""
    to_geo, _ = _transformers(crs)
    lon, lat = to_geo.transform(e1, n1)
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise ValueError("Instrument station coordinates are invalid for the selected CRS.")
    if (e1, n1) == (e2, n2):
        raise ValueError("Instrument station and backsight coordinates are identical.")

    warnings = []
    if crs.utm_zone:
        # Offset from the central meridian is the same whichever zone is chosen, so this
        # flags implausible eastings, not a wrong zone (see utm_zone_mismatch for that).
        cm = int(crs.utm_zone[:-1]) * 6 - 183
        if abs(normalize_angle(lon - cm)) > 3.5:
            warnings.append(
                f"Station is {abs(normalize_angle(lon - cm)):.1f}° from the central meridian, "
                "outside the normal UTM zone width; check the easting."
            )
        if not 100_000 <= e1 <= 900_000:
            warnings.append("Easting is outside the normal UTM range (100 000 - 900 000 m).")

    return GridValues(
        bearing=grid_bearing(e1, n1, e2, n2),
        convergence=grid_convergence(crs, e1, n1),
        lon=lon,
        lat=lat,
        crs_name=crs.name,
        warnings=warnings,
    )
