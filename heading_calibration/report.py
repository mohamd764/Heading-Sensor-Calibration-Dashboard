"""HTML / PDF report generation."""

from __future__ import annotations

import io
from html import escape

from xhtml2pdf import pisa

from .calibration import RESULT_COLUMNS, CalibrationResult

_CSS = """
@page { size: letter landscape; margin: 1.5cm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9pt; color: #222; }
h1 { font-size: 16pt; margin-bottom: 2pt; }
h2 { font-size: 12pt; margin-top: 12pt; border-bottom: 1px solid #999; }
table { width: 100%; }
th, td { border: 1px solid #bbb; padding: 3pt; text-align: left; }
th { background-color: #e6e6e6; }
.warn { color: #a15c00; }
.muted { color: #666; font-size: 8pt; }
"""


def _fmt(value, spec):
    return "N/A" if value is None else format(value, spec)


def stats_lines(result: CalibrationResult):
    s = result.stats
    lines = [
        f"Observations entered: {result.total_rows}",
        f"Successful reductions: {result.successful_rows}",
        f"Failed reductions: {result.failed_rows}",
        f"Bow/Stem heading comparisons (C-O): {s['n']}",
    ]
    if s["n"]:
        lines += [
            f"Mean (C-O): {_fmt(s['mean'], '+.3f')}°",
            f"Std Dev (C-O, n-1): {_fmt(s['std'], '.3f')}°",
            f"Range (C-O): {_fmt(s['min'], '+.3f')}° to {_fmt(s['max'], '+.3f')}°",
        ]
    return lines


def build_report_html(job_details: dict, result: CalibrationResult, title="Heading Sensor Calibration Report"):
    job_rows = "".join(
        f"<tr><th>{escape(str(k))}</th><td>{escape('' if v is None else str(v))}</td></tr>"
        for k, v in job_details.items()
    )
    head = "".join(f"<th>{escape(c)}</th>" for c in RESULT_COLUMNS)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(r[c]))}</td>" for c in RESULT_COLUMNS) + "</tr>"
        for r in result.table_rows()
    )
    stats = "".join(f"<li>{escape(line)}</li>" for line in stats_lines(result))
    warnings = "".join(f'<p class="warn">Warning: {escape(w)}</p>' for w in result.warnings)
    return f"""<html><head><meta charset="utf-8"><style>{_CSS}</style></head><body>
<h1>{escape(title)}</h1>
<p class="muted">Calculated true heading = grid heading (Stem to Bow) + grid convergence. C-O = calculated - observed.</p>
{warnings}
<h2>Job Details</h2><table>{job_rows}</table>
<h2>Statistical Analysis</h2><ul>{stats}</ul>
<h2>Observations and Results</h2><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
</body></html>"""


def html_to_pdf(html: str) -> bytes:
    buffer = io.BytesIO()
    status = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
    if status.err:
        raise RuntimeError("PDF generation failed.")
    return buffer.getvalue()
