import base64

import pytest

import app as dashboard
from heading_calibration.report import build_report_html, html_to_pdf


def sample_form():
    values = dashboard.load_sample_values()
    fill_ids = [o.component_id for o in dashboard.FILL_OUTPUTS]
    by_id = dict(zip(fill_ids, values))
    state_ids = [s.component_id for s in dashboard.FORM_STATES]
    return [by_id.get(i) for i in state_ids]


def test_form_states_and_keys_align():
    assert len(dashboard.FORM_STATES) == len(dashboard.FORM_KEYS)
    assert len(dashboard.FILL_OUTPUTS) == len(dashboard.load_sample_values())


def test_submit_with_sample_data():
    results, stats, details = dashboard.submit_data(1, *sample_form())
    text = str(stats)
    assert "Bow/Stem heading comparisons (C-O): 10" in text
    assert "Mean (C-O): +0.3" in text
    assert "WGS 84 / UTM zone 15N" in str(details)
    assert "Alert" not in str(stats)


def test_submit_warns_when_zone_disagrees_with_approx_position():
    values = sample_form()
    values[dashboard.FORM_KEYS.index("approx_lat")] = 37.75
    values[dashboard.FORM_KEYS.index("approx_lon")] = -122.4
    _, stats, _ = dashboard.submit_data(1, *values)
    assert "Approximate position is in UTM zone 10N, but zone 15N is selected." in str(stats)


def test_submit_reports_missing_crs():
    values = sample_form()
    values[dashboard.FORM_KEYS.index("zone")] = None
    results, stats, details = dashboard.submit_data(1, *values)
    assert "UTM zone" in str(results)


def test_export_pdf_callback_returns_pdf():
    download, status = dashboard.export_pdf(1, *sample_form())
    assert status is None
    assert download["filename"] == "DEMO-0001_report.pdf"
    pdf = base64.b64decode(download["content"])
    assert pdf.startswith(b"%PDF")


def test_export_pdf_reports_errors():
    values = sample_form()
    values[dashboard.FORM_KEYS.index("e1")] = None
    download, status = dashboard.export_pdf(1, *values)
    assert "Cannot export PDF" in str(status)


def test_report_html_escapes_user_input():
    form = dict(zip(dashboard.FORM_KEYS, sample_form()))
    form["client"] = "<script>alert(1)</script>"
    job_details, result = dashboard.compute(form)
    html = build_report_html(job_details, result)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert html_to_pdf(html).startswith(b"%PDF")


@pytest.mark.parametrize("lat, lon, expected", [(29.8, -95.6, ("15", "North", "utm")), (None, 1, (dashboard.no_update,) * 3)])
def test_suggest_zone(lat, lon, expected):
    assert dashboard.suggest_zone(1, lat, lon) == expected


def test_grid_value_callback():
    bearing, convergence, status, warnings = dashboard.update_grid_values(
        250000, 3300000, 249879.512, 3300310.184, "utm", "15", "North", None
    )
    assert convergence.startswith("-001° 17'")
    assert warnings is None
    *_, warnings = dashboard.update_grid_values(
        250000, 3300000, 249879.512, 3300310.184, "utm", "15", "North", None, 37.75, -122.4
    )
    assert "zone 10N" in str(warnings)
    assert dashboard.update_grid_values(1, 1, 2, 2, "epsg", None, None, None)[0] == "N/A"
