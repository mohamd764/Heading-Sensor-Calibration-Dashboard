import math

import pytest
from pyproj import Transformer

from heading_calibration.geodesy import (
    calculate_grid_values,
    decimal_to_dms,
    dms_to_decimal,
    grid_bearing,
    grid_convergence,
    normalize_angle,
    resolve_projected_crs,
    utm_epsg,
    utm_zone_from_lonlat,
)

ARCSEC = 1 / 3600


def dms(d, m, s, sign=1):
    return sign * (d + m / 60 + s / 3600)


# Worked examples from the Geocentric Datum of Australia (GDA94) Technical
# Manual (ICSM), "Redfearn's formulae" section. Both are Transverse Mercator
# (MGA = UTM on GRS80), so they exercise exactly the UTM convergence math.
GDA_REFERENCE = [
    # name, epsg, lat, lon, published E, published N, published convergence
    ("Flinders Peak", 28355, dms(37, 57, 3.7203, -1), dms(144, 25, 29.5244), 273741.297, 5796489.777, dms(1, 35, 3.65)),
    ("Buninyong", 28354, dms(37, 39, 10.1561, -1), dms(143, 55, 35.3839), 758173.797, 5828674.340, dms(1, 47, 19.36, -1)),
]


@pytest.mark.parametrize("name, epsg, lat, lon, east, north, gamma", GDA_REFERENCE)
def test_published_projection_coordinates(name, epsg, lat, lon, east, north, gamma):
    e, n = Transformer.from_crs("EPSG:4283", f"EPSG:{epsg}", always_xy=True).transform(lon, lat)
    assert e == pytest.approx(east, abs=0.001)
    assert n == pytest.approx(north, abs=0.001)


@pytest.mark.parametrize("name, epsg, lat, lon, east, north, gamma", GDA_REFERENCE)
def test_published_grid_convergence(name, epsg, lat, lon, east, north, gamma):
    crs = resolve_projected_crs(epsg=epsg)
    assert grid_convergence(crs, east, north) == pytest.approx(gamma, abs=0.01 * ARCSEC)


@pytest.mark.parametrize("name, epsg, lat, lon, east, north, gamma", GDA_REFERENCE)
def test_published_convergence_via_wgs84_utm_zone(name, epsg, lat, lon, east, north, gamma):
    zone, hemisphere = utm_zone_from_lonlat(lon, lat)
    assert zone == epsg - 28300 and hemisphere == "South"
    crs = resolve_projected_crs(zone=zone, hemisphere=hemisphere)
    # WGS84 vs GRS80 ellipsoid differences are far below 0.01".
    assert grid_convergence(crs, east, north) == pytest.approx(gamma, abs=0.01 * ARCSEC)


def old_zone_from_easting(easting):
    return int((easting // 1000000) % 60) + 1


@pytest.mark.parametrize("easting", [166_000, 273_741.297, 500_000, 758_173.797, 833_000])
def test_regression_old_zone_formula_always_returned_zone_1(easting):
    assert old_zone_from_easting(easting) == 1


def test_convergence_is_zero_on_central_meridian_and_equator():
    crs = resolve_projected_crs(zone=15, hemisphere="North")
    assert grid_convergence(crs, 500_000, 3_300_000) == pytest.approx(0, abs=1e-6)
    assert grid_convergence(crs, 300_000, 0) == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("zone, hemisphere, easting, northing, expected_sign", [
    (15, "North", 700_000, 3_300_000, +1),
    (15, "North", 300_000, 3_300_000, -1),
    (56, "South", 700_000, 6_250_000, -1),
    (56, "South", 300_000, 6_250_000, +1),
])
def test_convergence_sign_convention(zone, hemisphere, easting, northing, expected_sign):
    gamma = grid_convergence(resolve_projected_crs(zone=zone, hemisphere=hemisphere), easting, northing)
    assert math.copysign(1, gamma) == expected_sign


def test_convergence_matches_series_formula_for_utm():
    # gamma ~= atan(tan(dlon) * sin(lat)) is accurate to < 0.2" inside a UTM zone.
    crs = resolve_projected_crs(zone=10, hemisphere="North")
    for e, n in [(250_000, 4_200_000), (620_000, 5_300_000), (410_000, 3_600_000)]:
        g = calculate_grid_values(e, n, e + 1, n + 1, crs)
        dlon = math.radians(g.lon - (10 * 6 - 183))
        approx = math.degrees(math.atan(math.tan(dlon) * math.sin(math.radians(g.lat))))
        assert g.convergence == pytest.approx(approx, abs=0.2 * ARCSEC)


def test_state_plane_convergence_differs_from_utm_assumption():
    # NAD83 / California zone 3 (ftUS), a Lambert Conformal Conic grid: the old
    # code (treating any easting as UTM zone 1) was wrong by >14 degrees here.
    crs = resolve_projected_crs(epsg=2227)
    to_grid = Transformer.from_crs("EPSG:4269", crs, always_xy=True)
    lon, lat = -122.4, 37.75
    e, n = to_grid.transform(lon, lat)
    # LCC convergence = (lon - lon0) * sin(lat0); zone 3: lon0 = -120.5, n = sin(phi0) of the cone.
    cone = crs.coordinate_operation.params
    lat1 = next(p.value for p in cone if "1st standard parallel" in p.name)
    lat2 = next(p.value for p in cone if "2nd standard parallel" in p.name)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    # Spherical cone constant is adequate to ~1" at this offset from the CM.
    cone_n = math.log(math.cos(p1) / math.cos(p2)) / math.log(math.tan(math.pi / 4 + p2 / 2) / math.tan(math.pi / 4 + p1 / 2))
    expected = (lon - -120.5) * cone_n
    assert grid_convergence(crs, e, n) == pytest.approx(expected, abs=0.01)


def test_utm_zone_from_lonlat():
    assert utm_zone_from_lonlat(-95.6, 29.8) == (15, "North")
    assert utm_zone_from_lonlat(151.2, -33.9) == (56, "South")
    assert utm_zone_from_lonlat(-180, 0) == (1, "North")
    assert utm_zone_from_lonlat(180, 0) == (60, "North")
    assert utm_zone_from_lonlat(5, 60) == (32, "North")  # Norway exception
    assert utm_zone_from_lonlat(10, 78) == (33, "North")  # Svalbard exception
    with pytest.raises(ValueError):
        utm_zone_from_lonlat(0, 85)


def test_resolve_crs_validation():
    assert utm_epsg(15, "North") == 32615
    assert utm_epsg("56", "South") == 32756
    assert resolve_projected_crs(zone=1, hemisphere="North", epsg=26915).to_epsg() == 26915
    for kwargs in ({"zone": 0, "hemisphere": "North"}, {"zone": 61, "hemisphere": "South"},
                   {"zone": 10, "hemisphere": "west"}, {"epsg": 4326}, {"epsg": 999999}):
        with pytest.raises(ValueError):
            resolve_projected_crs(**kwargs)


def test_wrong_zone_warning():
    crs = resolve_projected_crs(zone=15, hemisphere="North")
    assert calculate_grid_values(500_000, 3_300_000, 500_010, 3_300_100, crs).warnings == []
    assert calculate_grid_values(50_000, 3_300_000, 50_010, 3_300_100, crs).warnings


def test_grid_bearing_quadrants():
    assert grid_bearing(0, 0, 0, 10) == pytest.approx(0)
    assert grid_bearing(0, 0, 10, 0) == pytest.approx(90)
    assert grid_bearing(0, 0, 0, -10) == pytest.approx(180)
    assert grid_bearing(0, 0, -10, 0) == pytest.approx(270)


def test_dms_round_trip_and_formatting():
    assert dms_to_decimal(12, 30, 36) == pytest.approx(12.51)
    assert dms_to_decimal(10, 60, 0) is None
    assert dms_to_decimal(None, 0, 0) is None
    assert decimal_to_dms(12.51) == "012° 30' 36.00''"
    assert decimal_to_dms(dms(1, 47, 19.36, -1)) == "-001° 47' 19.36''"
    assert decimal_to_dms(59.9999999) == "060° 00' 00.00''"
    assert decimal_to_dms(None) == "N/A"


def test_normalize_angle():
    assert normalize_angle(190) == pytest.approx(-170)
    assert normalize_angle(-190) == pytest.approx(170)
    assert normalize_angle(359.5 - 0.5) == pytest.approx(-1)
