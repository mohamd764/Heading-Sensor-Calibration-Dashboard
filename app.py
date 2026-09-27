"""Heading Sensor Calibration dashboard (Dash).

Run with ``python app.py`` and open http://127.0.0.1:8050.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dash_table, dcc, html, no_update

from heading_calibration.calibration import RESULT_COLUMNS, reduce_observations
from heading_calibration.geodesy import (
    calculate_grid_values,
    dms_to_decimal,
    resolve_projected_crs,
    utm_zone_from_lonlat,
)
from heading_calibration.report import build_report_html, html_to_pdf, stats_lines

SAMPLE_JOB = Path(__file__).resolve().parent / "sample_data" / "sample_job.json"
N_ROWS = 20


def empty_rows(n=N_ROWS):
    return [
        {
            "utc_time": "",
            "obs_point": "Bow" if i % 2 == 0 else "Stem",
            "direction_deg": None,
            "direction_min": None,
            "direction_sec": None,
            "obs_distance": None,
            "obs_true_heading": None,
        }
        for i in range(n)
    ]


def dms_input(id_prefix):
    fields = [("degrees", "Degrees", 0, 360, 1), ("minutes", "Minutes", 0, 59, 1), ("seconds", "Seconds", 0, 59.99, 0.01)]
    return dbc.Row([
        dbc.Col(dbc.Input(id=f"{id_prefix}-{suffix}", placeholder=label, type="number", min=lo, max=hi, step=step), width=4)
        for suffix, label, lo, hi, step in fields
    ], className="mb-2")


def labelled(label, component, width=3):
    return dbc.Col([html.H6(label), component], width=width)


def card(title, *children):
    return dbc.Card([dbc.CardHeader(html.H5(title)), dbc.CardBody(list(children))], className="mb-4")


JOB_FIELDS = [
    ("job-number", "Job Number"),
    ("job-description", "Job Description"),
    ("client", "Client"),
    ("party-chief", "Party Chief"),
    ("surveyor", "Surveyor"),
    ("wharf", "Wharf / Berth"),
    ("vessel", "Vessel"),
]

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP], title="Heading Sensor Calibration")
server = app.server

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.H1("Heading Sensor Calibration"),
            html.P(
                "Compare a vessel's gyrocompass / heading sensor with the true heading derived from "
                "total-station observations to Bow and Stem prisms.",
                className="text-muted",
            ),
        ], md=8),
        dbc.Col([
            dbc.Button("Load sample data", id="load-sample", color="outline-primary", className="me-2"),
            dbc.Button("Clear", id="clear-form", color="outline-secondary"),
        ], md=4, className="text-md-end align-self-center"),
    ], className="my-4"),

    card(
        "Job Details",
        dbc.Row([labelled(label, dbc.Input(id=fid)) for fid, label in JOB_FIELDS[:4]]),
        dbc.Row([labelled(label, dbc.Input(id=fid)) for fid, label in JOB_FIELDS[4:]] + [
            labelled("Date", dcc.DatePickerSingle(id="date", placeholder="Select a date", display_format="YYYY-MM-DD")),
        ], className="mt-2"),
        dbc.Row([labelled("Heading Sensor / Device", dbc.Input(id="device-name"))], className="mt-2"),
    ),

    card(
        "Coordinate Reference System",
        html.P(
            "Grid convergence depends on the projection of the station coordinates. The UTM zone "
            "cannot be recovered from an easting, so select it explicitly or enter an EPSG code.",
            className="text-muted small",
        ),
        dbc.RadioItems(
            id="crs-mode",
            options=[{"label": "UTM zone + hemisphere (WGS 84)", "value": "utm"}, {"label": "EPSG code", "value": "epsg"}],
            value="utm",
            inline=True,
            className="mb-2",
        ),
        dbc.Row([
            labelled("UTM Zone", dbc.Select(id="utm-zone", options=[{"label": str(z), "value": str(z)} for z in range(1, 61)], placeholder="Zone")),
            labelled("Hemisphere", dbc.Select(id="hemisphere", options=[{"label": h, "value": h} for h in ("North", "South")], placeholder="Hemisphere")),
            labelled("EPSG Code", dbc.Input(id="epsg", type="number", placeholder="e.g. 26915, 2227, 28355")),
        ]),
        dbc.Row([
            labelled("Approx. Latitude", dbc.Input(id="approx-lat", type="number", placeholder="e.g. 29.8")),
            labelled("Approx. Longitude", dbc.Input(id="approx-lon", type="number", placeholder="e.g. -95.6")),
            dbc.Col(dbc.Button("Suggest UTM zone", id="suggest-zone", color="link"), width=3, className="align-self-end"),
        ], className="mt-2"),
        html.Div(id="crs-status", className="mt-2 small"),
    ),

    card(
        "Instrument Station",
        dbc.Row([
            labelled("Station Name", dbc.Input(id="instrument-station"), 3),
            labelled("Easting", dbc.Input(id="easting", type="number"), 3),
            labelled("Northing", dbc.Input(id="northing", type="number"), 3),
            labelled("Height (m)", dbc.Input(id="height", type="number"), 3),
        ]),
    ),

    card(
        "Backsight Station",
        dbc.Row([
            labelled("Station Name", dbc.Input(id="backsight-station"), 3),
            labelled("Easting", dbc.Input(id="backsight-easting", type="number"), 3),
            labelled("Northing", dbc.Input(id="backsight-northing", type="number"), 3),
            labelled("Height (m)", dbc.Input(id="backsight-height", type="number"), 3),
        ]),
    ),

    dbc.Row([
        dbc.Col(card("Grid Bearing (Station to Backsight)", html.Div(id="grid-bearing-output", className="fw-bold fs-5")), md=6),
        dbc.Col(card("Grid Convergence at Station", html.Div(id="grid-convergence-output", className="fw-bold fs-5")), md=6),
    ]),
    html.Div(id="grid-warnings"),

    card("Backsight Observation (horizontal direction, DMS)", dms_input("backsight-observation")),

    card(
        f"Observations ({N_ROWS} rows, Bow followed by Stem)",
        dash_table.DataTable(
            id="gyro-table",
            columns=[
                {"name": "UTC Time (hh:mm:ss)", "id": "utc_time", "type": "text"},
                {"name": "Observation Point", "id": "obs_point", "type": "text", "editable": False},
                {"name": "Direction Deg", "id": "direction_deg", "type": "numeric"},
                {"name": "Direction Min", "id": "direction_min", "type": "numeric"},
                {"name": "Direction Sec", "id": "direction_sec", "type": "numeric"},
                {"name": "Horizontal Distance (m)", "id": "obs_distance", "type": "numeric"},
                {"name": "Observed Heading (°, Bow rows)", "id": "obs_true_heading", "type": "numeric"},
            ],
            data=empty_rows(),
            editable=True,
            style_cell={"minWidth": "100px", "whiteSpace": "normal", "textAlign": "left"},
            style_header={"backgroundColor": "rgb(230, 230, 230)", "fontWeight": "bold"},
        ),
    ),

    dbc.Row(dbc.Col([
        dbc.Button("Calculate", id="submit-button", color="primary", className="me-2", n_clicks=0),
        dbc.Button("Export to PDF", id="export-pdf-button", color="secondary", n_clicks=0),
        dcc.Download(id="download-pdf"),
        html.Div(id="export-status", className="mt-2"),
    ], className="text-center"), className="mb-4"),

    dbc.Row(dbc.Col([html.H4("Statistical Analysis"), html.Div(id="statistical-analysis")]), className="mb-4"),
    dbc.Row(dbc.Col([html.H4("Calculated Results"), html.Div(id="results-table")]), className="mb-4"),
    dbc.Row(dbc.Col([html.H4("Job Details"), html.Div(id="submitted-job-details")]), className="mb-4"),
], fluid=True)


# ------------------------------------------------------------------ helpers

CRS_STATES = [State("crs-mode", "value"), State("utm-zone", "value"), State("hemisphere", "value"), State("epsg", "value")]
FORM_STATES = (
    [State(fid, "value") for fid, _ in JOB_FIELDS]
    + [State("date", "date"), State("device-name", "value")]
    + CRS_STATES
    + [State(i, "value") for i in (
        "instrument-station", "easting", "northing", "height",
        "backsight-station", "backsight-easting", "backsight-northing", "backsight-height",
        "backsight-observation-degrees", "backsight-observation-minutes", "backsight-observation-seconds",
    )]
    + [State("gyro-table", "data")]
)
FORM_KEYS = (
    [fid.replace("-", "_") for fid, _ in JOB_FIELDS]
    + ["date", "device_name", "crs_mode", "zone", "hemisphere", "epsg",
       "station", "e1", "n1", "h1", "backsight", "e2", "n2", "h2", "bs_deg", "bs_min", "bs_sec", "rows"]
)


def crs_from_inputs(mode, zone, hemisphere, epsg):
    if mode == "epsg":
        if epsg in (None, ""):
            raise ValueError("Enter an EPSG code for the projected CRS.")
        return resolve_projected_crs(epsg=epsg)
    if not zone or not hemisphere:
        raise ValueError("Select the UTM zone and hemisphere.")
    return resolve_projected_crs(zone=zone, hemisphere=hemisphere)


def compute(form):
    """Validate the form and run the reduction. Returns (job_details, result)."""
    missing = [label for key, label in (
        ("e1", "station easting"), ("n1", "station northing"),
        ("e2", "backsight easting"), ("n2", "backsight northing"),
        ("bs_deg", "backsight degrees"), ("bs_min", "backsight minutes"), ("bs_sec", "backsight seconds"),
    ) if form[key] is None]
    if missing:
        raise ValueError("Missing required input: " + ", ".join(missing) + ".")
    crs = crs_from_inputs(form["crs_mode"], form["zone"], form["hemisphere"], form["epsg"])
    backsight_dd = dms_to_decimal(form["bs_deg"], form["bs_min"], form["bs_sec"])
    if backsight_dd is None:
        raise ValueError("Backsight observation (DMS) is invalid.")
    grid = calculate_grid_values(form["e1"], form["n1"], form["e2"], form["n2"], crs)
    result = reduce_observations(form["rows"], form["e1"], form["n1"], backsight_dd, grid)

    job_details = {label: form[fid.replace("-", "_")] for fid, label in JOB_FIELDS}
    job_details.update({
        "Date": form["date"],
        "Heading Sensor / Device": form["device_name"],
        "Coordinate Reference System": f"{grid.crs_name} (EPSG:{crs.to_epsg()})",
        "Station": f"{form['station'] or ''}  E {form['e1']}  N {form['n1']}  H {form['h1']}",
        "Backsight": f"{form['backsight'] or ''}  E {form['e2']}  N {form['n2']}  H {form['h2']}",
        "Station Latitude / Longitude": f"{grid.lat:.6f}, {grid.lon:.6f}",
        "Grid Bearing (Station to Backsight)": grid.bearing_dms,
        "Grid Convergence at Station": grid.convergence_dms,
    })
    return job_details, result


def html_table(header, rows):
    return dbc.Table(
        [html.Thead(html.Tr([html.Th(h) for h in header]))] + [html.Tbody([html.Tr([html.Td(c) for c in r]) for r in rows])],
        bordered=True, striped=True, size="sm", responsive=True,
    )


# ------------------------------------------------------------------ callbacks


@app.callback(
    Output("grid-bearing-output", "children"),
    Output("grid-convergence-output", "children"),
    Output("crs-status", "children"),
    Output("grid-warnings", "children"),
    Input("easting", "value"),
    Input("northing", "value"),
    Input("backsight-easting", "value"),
    Input("backsight-northing", "value"),
    Input("crs-mode", "value"),
    Input("utm-zone", "value"),
    Input("hemisphere", "value"),
    Input("epsg", "value"),
)
def update_grid_values(e1, n1, e2, n2, mode, zone, hemisphere, epsg):
    try:
        crs = crs_from_inputs(mode, zone, hemisphere, epsg)
    except ValueError as exc:
        return "N/A", "N/A", html.Span(str(exc), className="text-danger"), None
    status = html.Span(f"Using {crs.name} (EPSG:{crs.to_epsg()})", className="text-success")
    if None in (e1, n1, e2, n2):
        return "N/A", "N/A", status, None
    try:
        grid = calculate_grid_values(e1, n1, e2, n2, crs)
    except ValueError as exc:
        return "N/A", "N/A", status, dbc.Alert(str(exc), color="danger")
    warnings = [dbc.Alert(w, color="warning") for w in grid.warnings] or None
    return grid.bearing_dms, grid.convergence_dms, status, warnings


@app.callback(
    Output("utm-zone", "value", allow_duplicate=True),
    Output("hemisphere", "value", allow_duplicate=True),
    Output("crs-mode", "value", allow_duplicate=True),
    Input("suggest-zone", "n_clicks"),
    State("approx-lat", "value"),
    State("approx-lon", "value"),
    prevent_initial_call=True,
)
def suggest_zone(_, lat, lon):
    if lat is None or lon is None:
        return no_update, no_update, no_update
    try:
        zone, hemisphere = utm_zone_from_lonlat(float(lon), float(lat))
    except ValueError:
        return no_update, no_update, no_update
    return str(zone), hemisphere, "utm"


FILL_OUTPUTS = (
    [Output(fid, "value", allow_duplicate=True) for fid, _ in JOB_FIELDS]
    + [Output("date", "date"), Output("device-name", "value")]
    + [Output(i, "value", allow_duplicate=True) for i in ("crs-mode", "utm-zone", "hemisphere")]
    + [Output(i, "value") for i in (
        "epsg", "instrument-station", "easting", "northing", "height",
        "backsight-station", "backsight-easting", "backsight-northing", "backsight-height",
        "backsight-observation-degrees", "backsight-observation-minutes", "backsight-observation-seconds",
    )]
    + [Output("gyro-table", "data")]
)


def load_sample_values(path=SAMPLE_JOB):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    job, crs, ins, bs, bso = data["job"], data["crs"], data["instrument"], data["backsight"], data["backsight_observation"]
    rows = data["observations"] + empty_rows(N_ROWS)[len(data["observations"]):]
    return (
        [job[fid.replace("-", "_")] for fid, _ in JOB_FIELDS]
        + [job["date"], job["device_name"], crs["mode"], str(crs["zone"]), crs["hemisphere"], crs["epsg"]]
        + [ins["name"], ins["easting"], ins["northing"], ins["height"]]
        + [bs["name"], bs["easting"], bs["northing"], bs["height"]]
        + [bso["deg"], bso["min"], bso["sec"], rows]
    )


@app.callback(*FILL_OUTPUTS, Input("load-sample", "n_clicks"), Input("clear-form", "n_clicks"), prevent_initial_call=True)
def fill_form(_, __):
    if dash.ctx.triggered_id == "load-sample":
        return load_sample_values()
    return [None] * (len(JOB_FIELDS) + 2) + ["utm", None, None] + [None] * 12 + [empty_rows()]


@app.callback(
    Output("results-table", "children"),
    Output("statistical-analysis", "children"),
    Output("submitted-job-details", "children"),
    Input("submit-button", "n_clicks"),
    *FORM_STATES,
    prevent_initial_call=True,
)
def submit_data(n_clicks, *values):
    try:
        job_details, result = compute(dict(zip(FORM_KEYS, values)))
    except ValueError as exc:
        return dbc.Alert(str(exc), color="danger"), "", ""
    rows = result.table_rows()
    results = html_table(RESULT_COLUMNS, [[r[c] for c in RESULT_COLUMNS] for r in rows]) if rows else html.Div(
        "No valid observations to display."
    )
    stats = html.Ul([html.Li(s) for s in stats_lines(result)], className="fw-bold")
    details = html_table(["Field", "Value"], [[k, "" if v is None else str(v)] for k, v in job_details.items()])
    return results, stats, details


@app.callback(
    Output("download-pdf", "data"),
    Output("export-status", "children"),
    Input("export-pdf-button", "n_clicks"),
    *FORM_STATES,
    prevent_initial_call=True,
)
def export_pdf(n_clicks, *values):
    form = dict(zip(FORM_KEYS, values))
    try:
        job_details, result = compute(form)
        pdf = html_to_pdf(build_report_html(job_details, result))
    except (ValueError, RuntimeError) as exc:
        return no_update, dbc.Alert(f"Cannot export PDF: {exc}", color="danger")
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (form["job_number"] or "heading_calibration"))
    return dcc.send_bytes(pdf, f"{stem}_report.pdf"), None


if __name__ == "__main__":
    app.run(debug=os.environ.get("DASH_DEBUG", "0") == "1")
