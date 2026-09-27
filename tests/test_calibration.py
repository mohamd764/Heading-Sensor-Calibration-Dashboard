import json
import math
from pathlib import Path

import pytest

from heading_calibration.calibration import reduce_observations
from heading_calibration.geodesy import (
    calculate_grid_values,
    dms_to_decimal,
    grid_bearing,
    resolve_projected_crs,
)

SAMPLE = json.loads((Path(__file__).resolve().parents[1] / "sample_data" / "sample_job.json").read_text())


def run_sample(job=SAMPLE):
    crs = resolve_projected_crs(zone=job["crs"]["zone"], hemisphere=job["crs"]["hemisphere"])
    ins, bs, bso = job["instrument"], job["backsight"], job["backsight_observation"]
    grid = calculate_grid_values(ins["easting"], ins["northing"], bs["easting"], bs["northing"], crs)
    return grid, reduce_observations(
        job["observations"], ins["easting"], ins["northing"], dms_to_decimal(bso["deg"], bso["min"], bso["sec"]), grid
    )


def test_sample_job_recovers_simulated_sensor_error():
    grid, result = run_sample()
    assert grid.convergence == pytest.approx(SAMPLE["expected"]["grid_convergence_deg"], abs=1e-6)
    stats = result.stats
    assert stats["n"] == 10
    assert result.total_rows == result.successful_rows == 20
    assert stats["mean"] == pytest.approx(SAMPLE["expected"]["mean_c_minus_o_deg"], abs=0.03)
    assert 0 < stats["std"] < 0.06


def test_convergence_error_propagates_one_to_one_into_c_minus_o():
    grid, reference = run_sample()
    gamma, grid.convergence = grid.convergence, 0.0
    ins, bso = SAMPLE["instrument"], SAMPLE["backsight_observation"]
    no_gamma = reduce_observations(SAMPLE["observations"], ins["easting"], ins["northing"],
                                   dms_to_decimal(bso["deg"], bso["min"], bso["sec"]), grid)
    shift = reference.stats["mean"] - no_gamma.stats["mean"]
    assert shift == pytest.approx(gamma, abs=1e-9)


def make_obs(station, backsight, bow, stem, observed, backsight_reading=0.0):
    """Synthesise perfect Bow/Stem observations for a known geometry."""
    bs_bearing = grid_bearing(*station, *backsight)
    rows = []
    for label, pt, obs in (("Bow", bow, observed), ("Stem", stem, None)):
        direction = (backsight_reading + grid_bearing(*station, *pt) - bs_bearing) % 360
        d = int(direction)
        m = int((direction - d) * 60)
        s = ((direction - d) * 60 - m) * 60
        rows.append({"utc_time": "00:00:00", "obs_point": label, "direction_deg": d, "direction_min": m,
                     "direction_sec": s, "obs_distance": math.dist(station, pt), "obs_true_heading": obs})
    return rows


@pytest.mark.parametrize("grid_heading", [0.0, 45.0, 135.0, 225.0, 359.0])
def test_calculated_heading_is_grid_heading_plus_convergence(grid_heading):
    crs = resolve_projected_crs(zone=56, hemisphere="South")
    station, backsight = (320_000.0, 6_250_000.0), (320_100.0, 6_250_300.0)
    grid = calculate_grid_values(*station, *backsight, crs)
    h = math.radians(grid_heading)
    centre = (station[0] + 40, station[1] + 25)
    bow = (centre[0] + 30 * math.sin(h), centre[1] + 30 * math.cos(h))
    stem = (centre[0] - 30 * math.sin(h), centre[1] - 30 * math.cos(h))
    true_heading = (grid_heading + grid.convergence) % 360
    rows = make_obs(station, backsight, bow, stem, observed=(true_heading - 0.5) % 360, backsight_reading=123.456)
    result = reduce_observations(rows, *station, 123.456, grid)

    assert result.comparisons[0].calculated == pytest.approx(true_heading, abs=1e-7)
    assert result.c_minus_o[0] == pytest.approx(0.5, abs=1e-7)
    assert result.points[0].easting == pytest.approx(bow[0], abs=1e-6)
    assert result.points[1].northing == pytest.approx(stem[1], abs=1e-6)


def test_c_minus_o_wraps_across_north():
    crs = resolve_projected_crs(zone=15, hemisphere="North")
    station, backsight = (500_000.0, 3_300_000.0), (500_000.0, 3_300_500.0)
    grid = calculate_grid_values(*station, *backsight, crs)
    rows = make_obs(station, backsight, (500_010.0, 3_300_060.0), (500_010.0, 3_300_020.0), observed=359.8)
    result = reduce_observations(rows, *station, 0.0, grid)
    assert result.c_minus_o[0] == pytest.approx(0.2, abs=1e-6)


def test_blank_and_invalid_rows():
    grid, _ = run_sample()
    rows = [dict(r) for r in SAMPLE["observations"][:4]]
    rows[2]["direction_min"] = 75  # invalid minutes -> failed Bow, so that pair is skipped
    rows.append({"utc_time": "", "obs_point": "Bow", "direction_deg": None, "direction_min": None,
                 "direction_sec": None, "obs_distance": None, "obs_true_heading": None})
    ins, bso = SAMPLE["instrument"], SAMPLE["backsight_observation"]
    result = reduce_observations(rows, ins["easting"], ins["northing"],
                                 dms_to_decimal(bso["deg"], bso["min"], bso["sec"]), grid)
    assert (result.total_rows, result.successful_rows, result.failed_rows) == (4, 3, 1)
    assert len(result.comparisons) == 1
    assert result.stats["std"] is None
    table = result.table_rows()
    assert table[2]["Plane Bearing (DMS)"] == "N/A"
    assert table[3]["C - O (°)"] == "N/A"
