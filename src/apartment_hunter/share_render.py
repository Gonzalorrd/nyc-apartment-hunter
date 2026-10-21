"""Share-site rendering: plotly charts, the phone-first landing page, CSVs, run report.

Reads only the pipeline tables under share/_data/ (see `share_pipeline.py`). Colors are
the dataviz reference palette: slot 1 blue and slot 2 orange (validated colorblind-safe
as a pair), status colors with icon + label, and text ink that never wears a series color.
"""

import json
import math
import shutil
import tomllib
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from plotly.offline import get_plotlyjs_version

from apartment_hunter.exporting import csv_bytes

BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'
PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True, "scrollZoom": False}
ELIGIBILITY = {
    "eligible": {"label": "Fits every requirement", "icon": "✓", "color": BLUE},
    "needs_verification": {"label": "Needs checking", "icon": "?", "color": ORANGE},
    "excluded": {"label": "Ruled out", "icon": "✕", "color": MUTED},
}
CHARTS = ("building_map", "cost_vs_commute", "cost_breakdown", "neighborhood_counts")
EMPTY = {
    "building_map": "No building has an exact, geocoded address yet.",
    "cost_vs_commute": "No published unit has both a known monthly cost and a verified commute.",
    "cost_breakdown": "No published unit has a known base rent and mandatory fees yet.",
    "neighborhood_counts": "No buildings published yet.",
}


def money(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"${value:,.0f}" if float(value).is_integer() else f"${value:,.2f}"


def checked(days) -> str:
    if days is None or (isinstance(days, float) and math.isnan(days)):
        return "Not checked yet"
    days = int(days)
    return f"Checked {'today' if days == 0 else '1 day ago' if days == 1 else f'{days} days ago'}"


def present(value) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def style(fig: go.Figure, height: int) -> go.Figure:
    axis = {
        "gridcolor": GRID,
        "linecolor": AXIS,
        "zeroline": False,
        "tickfont": {"color": MUTED},
        "title": {"font": {"color": INK_2}},
    }
    fig.update_layout(
        height=height,
        font={"family": FONT, "size": 13, "color": INK_2},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        margin={"l": 8, "r": 16, "t": 8, "b": 8},
        hoverlabel={"bgcolor": "#ffffff", "bordercolor": GRID, "font": {"color": INK}},
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0, "title": None},
        xaxis=axis,
        yaxis=axis,
    )
    return fig


def building_map(buildings: pd.DataFrame, office: dict | None) -> go.Figure | None:
    mapped = buildings[buildings["map_latitude"].notna()]
    if mapped.empty:
        return None
    fig = go.Figure()
    has_fit = mapped["units_eligible"] > 0
    groups = (
        [
            ("Has an apartment that fits", mapped[has_fit], BLUE),
            ("Other buildings", mapped[~has_fit], MUTED),
        ]
        if has_fit.any()
        else [("Buildings", mapped, BLUE)]
    )
    for name, frame, color in groups:
        fig.add_trace(
            go.Scattermap(
                lat=frame["map_latitude"],
                lon=frame["map_longitude"],
                mode="markers",
                name=name,
                marker={"size": 13, "color": color},
                customdata=frame[["name", "neighborhood", "address", "management_company"]]
                .fillna("—")
                .values,
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>%{customdata[2]}"
                "<br>Managed by %{customdata[3]}<extra></extra>",
            )
        )
    lats, lons = list(mapped["map_latitude"]), list(mapped["map_longitude"])
    if office:
        lats.append(office["latitude"])
        lons.append(office["longitude"])
        fig.add_trace(
            go.Scattermap(
                lat=[office["latitude"]],
                lon=[office["longitude"]],
                mode="markers+text",
                name="Office",
                text=["Office"],
                textposition="top right",
                textfont={"color": INK, "size": 13},
                marker={"size": 16, "color": INK},
                hovertemplate=f"<b>Office</b><br>{office['address']}<extra></extra>",
            )
        )
    span = max(max(lons) - min(lons), (max(lats) - min(lats)) * 1.3, 0.01)
    fig.update_layout(
        map={
            "style": "carto-positron",
            "center": {"lat": (max(lats) + min(lats)) / 2, "lon": (max(lons) + min(lons)) / 2},
            # Fit the spread into ~320 px (narrowest phone we design for). MapLibre's world is
            # 512 px wide at zoom 0, so zoom z shows 320 * 360 / (512 * 2**z) degrees.
            "zoom": max(8.0, min(13.0, math.log2(320 * 360 / (512 * span)) - 0.2)),
        },
        showlegend=len(fig.data) > 1,
        legend={"bgcolor": "rgba(252,252,251,0.9)", "y": 0.99, "yanchor": "top", "x": 0.01},
    )
    style(fig, 440)
    fig.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0})
    return fig


def neighborhood_counts(neighborhoods: pd.DataFrame) -> go.Figure | None:
    if neighborhoods.empty:
        return None
    frame = neighborhoods.iloc[::-1]  # Largest at the top.
    fig = go.Figure(
        go.Bar(
            x=frame["buildings"],
            y=frame["neighborhood"],
            orientation="h",
            marker={"color": BLUE, "cornerradius": 4},
            text=frame["buildings"],
            textposition="outside",
            textfont={"color": INK_2},
            cliponaxis=False,
            hovertemplate="%{y}: %{x} buildings<extra></extra>",
        )
    )
    style(fig, 28 * len(frame) + 24)
    fig.update_layout(bargap=0.3, showlegend=False)
    fig.update_xaxes(visible=False, range=[0, frame["buildings"].max() * 1.15])
    fig.update_yaxes(gridcolor=SURFACE, tickfont={"color": INK_2}, automargin=True)
    return fig


def cost_vs_commute(units: pd.DataFrame, budget: float, max_commute: float) -> go.Figure | None:
    known = units[units["monthly_cost"].notna() & units["commute_minutes"].notna()]
    if known.empty:
        return None
    fig = go.Figure()
    fig.add_shape(
        type="rect",
        x0=0,
        x1=max_commute,
        y0=0,
        y1=budget,
        fillcolor=BLUE,
        opacity=0.06,
        line={"width": 0},
        layer="below",
    )
    for key, spec in ELIGIBILITY.items():
        frame = known[known["eligibility"] == key]
        if frame.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=frame["commute_minutes"],
                y=frame["monthly_cost"],
                mode="markers",
                name=spec["label"],
                marker={"size": 11, "color": spec["color"], "line": {"width": 2, "color": SURFACE}},
                customdata=frame[["building", "unit"]].values,
                hovertemplate="<b>$%{y:,.0f}</b> · %{x:.0f} min<br>%{customdata[0]} · "
                "unit %{customdata[1]}<extra></extra>",
            )
        )
    line = {"color": MUTED, "width": 1}
    fig.add_hline(y=budget, line=line, annotation_text=f"Budget {money(budget)}")
    fig.add_vline(x=max_commute, line=line, annotation_text=f"{max_commute:.0f} min")
    style(fig, 380)
    top = max(known["monthly_cost"].max(), budget) * 1.06
    fig.update_xaxes(title="Door-to-door commute (minutes)", rangemode="tozero")
    fig.update_yaxes(
        title="All-in monthly cost",
        tickprefix="$",
        tickformat=",.0f",
        range=[known["monthly_cost"].min() * 0.85, top],
    )
    fig.update_layout(margin={"l": 8, "r": 16, "t": 40, "b": 8}, hovermode="closest")
    return fig


def cost_breakdown(units: pd.DataFrame, budget: float) -> go.Figure | None:
    """Stacked bars, cheapest at the top. Labels sit above each bar so long building names
    don't squeeze the bars on a phone."""
    known = units[units["monthly_cost"].notna()].sort_values("monthly_cost", ascending=False)
    if known.empty:
        return None
    rows = [str(i) for i in range(len(known))]
    gap = {"width": 2, "color": SURFACE}
    fig = go.Figure(
        [
            go.Bar(
                x=known["base_rent"],
                y=rows,
                orientation="h",
                name="Base rent",
                marker={"color": BLUE, "line": gap},
                hovertemplate="Base rent <b>$%{x:,.0f}</b><extra></extra>",
            ),
            go.Bar(
                x=known["mandatory_fees"],
                y=rows,
                orientation="h",
                name="Mandatory fees",
                marker={"color": ORANGE, "line": gap, "cornerradius": 4},
                hovertemplate="Mandatory fees <b>$%{x:,.0f}</b><extra></extra>",
            ),
        ]
    )
    for row, unit in zip(rows, known.itertuples(), strict=True):
        fig.add_annotation(
            x=0,
            y=row,
            yshift=21,
            xanchor="left",
            showarrow=False,
            text=f"{unit.building} · {unit.unit}  <b>{money(unit.monthly_cost)}</b>",
            font={"color": INK_2},
        )
    fig.add_vline(
        x=budget,
        line={"color": MUTED, "width": 1},
        annotation_text=f"Budget {money(budget)}",
        annotation_position="bottom right",
    )
    style(fig, 52 * len(known) + 90)
    fig.update_layout(
        barmode="stack",
        bargap=0.6,
        margin={"l": 8, "r": 16, "t": 40, "b": 8},
        legend={"traceorder": "normal"},
    )
    fig.update_xaxes(
        tickprefix="$",
        tickformat="~s",
        range=[0, max(budget, known["monthly_cost"].max()) * 1.08],
    )
    fig.update_yaxes(visible=False)
    return fig


def figures(tables: dict[str, pd.DataFrame], summary: dict) -> dict[str, go.Figure | None]:
    return {
        "building_map": building_map(tables["buildings"], summary.get("office")),
        "cost_vs_commute": cost_vs_commute(
            tables["units"], summary["budget"], summary["max_commute"]
        ),
        "cost_breakdown": cost_breakdown(tables["units"], summary["budget"]),
        "neighborhood_counts": neighborhood_counts(tables["neighborhoods"]),
    }


def unit_cards(units: pd.DataFrame) -> list[dict]:
    return [
        {
            "title": f"{u.building} · unit {u.unit}",
            "neighborhood": u.neighborhood or "",
            "status": ELIGIBILITY[u.eligibility],
            "cost": money(u.monthly_cost) if present(u.monthly_cost) else None,
            "breakdown": f"{money(u.base_rent)} rent + {money(u.mandatory_fees)} fees"
            if present(u.monthly_cost)
            else "Rent or mandatory fees still unknown",
            "commute": f"{u.commute_minutes:.0f} min to the office"
            if present(u.commute_minutes)
            else "Commute not verified yet",
            "available": f"Available {u.available_date:%b} {u.available_date.day}"
            if isinstance(u.available_date, date)
            else "Move-in date unknown",
            "reasons": u.reasons,
            "checked": checked(u.days_since_verified),
            "url": u.listing_url,
        }
        for u in units.itertuples()
    ]


def building_rows(buildings: pd.DataFrame) -> list[dict]:
    rows = []
    for b in buildings.sort_values(["neighborhood", "name"], na_position="last").itertuples():
        place = ", ".join(p for p in (b.neighborhood, b.municipality, b.state) if p)
        rows.append(
            {
                "name": b.name,
                "place": place,
                "address": b.address or "No exact address yet",
                "management": b.management_company or "Management unknown",
                "checked": checked(b.days_since_verified),
                "stale": bool(b.stale),
                "mapped": present(b.map_latitude),
                "map_note": b.map_note,
                "units": int(b.units_published),
                "cheapest": money(b.cheapest_monthly_cost) if b.units_published else None,
                "url": b.listing_url or b.website or b.source_url,
                "search": f"{b.name} {place} {b.management_company or ''}".casefold(),
            }
        )
    return rows


def kpis(summary: dict) -> list[dict]:
    return [
        {"label": "Buildings researched", "value": f"{summary['buildings']:,}"},
        {"label": "On the map", "value": f"{summary['buildings_mapped']:,}"},
        {"label": "Apartments listed", "value": f"{summary['units']:,}"},
        {"label": "Fit every requirement", "value": f"{summary['units_eligible']:,}"},
        {"label": "Cheapest that fits", "value": money(summary["cheapest_eligible_cost"])},
    ]


def load_tables(data_dir: Path) -> tuple[dict[str, pd.DataFrame], dict]:
    tables = {
        name: pd.read_parquet(data_dir / f"{name}.parquet")
        for name in ("buildings", "units", "neighborhoods")
    }
    summary = json.loads((data_dir / "summary.json").read_text(encoding="utf-8"))
    return tables, summary


def chart_html(fig: go.Figure | None, name: str) -> Markup:
    if fig is None:
        return Markup('<p class="empty">{}</p>').format(EMPTY[name])
    html = fig.to_html(full_html=False, include_plotlyjs=False, config=PLOTLY_CONFIG)
    return Markup(html)  # Plotly escapes data strings inside its JSON payload.


def step_render(data_dir: Path, output_dir: Path, public_dir: Path, share_dir: Path) -> None:
    tables, summary = load_tables(data_dir)
    config = tomllib.loads((share_dir / "share.toml").read_text(encoding="utf-8"))
    figs = figures(tables, summary)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, fig in figs.items():  # Standalone chart files for the chartbook catalog.
        path = output_dir / f"{name}.html"
        if fig is None:
            path.write_text(f"<p>{EMPTY[name]}</p>\n", encoding="utf-8")
        else:
            fig.write_html(path, include_plotlyjs="cdn", config=PLOTLY_CONFIG)
    public_dir.mkdir(parents=True, exist_ok=True)
    buildings_csv = [c for c in tables["buildings"].columns if c not in ("building_id", "stale")]
    (public_dir / "buildings.csv").write_bytes(
        csv_bytes(records(tables["buildings"], buildings_csv), buildings_csv)
    )
    (public_dir / "units.csv").write_bytes(
        csv_bytes(records(tables["units"], UNITS_CSV), UNITS_CSV)
    )
    env = Environment(
        loader=FileSystemLoader(share_dir / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
    )
    as_of = date.fromisoformat(summary["as_of"])
    page = env.get_template("index.html.j2").render(
        config=config,
        summary=summary,
        as_of=f"{as_of:%B} {as_of.day}, {as_of.year}",
        budget=money(summary["budget"]),
        kpis=kpis(summary),
        cards=unit_cards(tables["units"]),
        buildings=building_rows(tables["buildings"]),
        charts={name: chart_html(fig, name) for name, fig in figs.items()},
        has_chart={name: fig is not None for name, fig in figs.items()},
        plotly_js=f"https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js",
    )
    (public_dir / "index.html").write_text(page, encoding="utf-8", newline="\n")
    (public_dir / ".nojekyll").touch()


UNITS_CSV = [
    "building",
    "neighborhood",
    "unit",
    "eligibility",
    "monthly_cost",
    "base_rent",
    "mandatory_fees",
    "net_effective_base_rent",
    "commute_minutes",
    "available_date",
    "square_feet",
    "status",
    "reasons",
    "warnings",
    "days_since_verified",
    "listing_url",
]


def records(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    """Rows for CSV export with missing values blank, never "nan"."""
    subset = frame[columns].astype(object)
    return subset.where(subset.notna(), None).to_dict("records")


def step_assemble(chartbook_docs: Path, public_dir: Path) -> None:
    target = public_dir / "pipeline"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(chartbook_docs, target)


def step_report(data_dir: Path, changes: dict, out_path: Path) -> None:
    """Markdown run summary; GitHub Actions appends it to the job summary page."""
    summary = json.loads((data_dir / "summary.json").read_text(encoding="utf-8"))
    enrich = json.loads((data_dir / "enrich.json").read_text(encoding="utf-8"))
    counts = json.loads((data_dir / "validation.json").read_text(encoding="utf-8"))
    lines = [
        f"## Share-site build for {summary['as_of']}",
        "",
        "| Step | Result |",
        "|---|---|",
        "| Validate | "
        + ", ".join(f"{n} {entity}" for entity, n in counts.items())
        + " passed the data contract and privacy gate |",
        f"| Enrich | {summary['buildings_mapped']} of {summary['buildings']} buildings mapped "
        f"({enrich['geocoded']} geocoded, {enrich['entered']} entered); "
        f"{enrich['no_address']} without an exact address, {enrich['no_match']} without a "
        f"reliable match, {enrich['errors']} geocoder errors; office pin: "
        f"{'yes' if enrich['office_mapped'] else 'no'} |",
        f"| Transform | {summary['units']} units ranked: {summary['units_eligible']} fit, "
        f"{summary['units_needs_verification']} need checking, "
        f"{summary['units_excluded']} ruled out |",
        "",
    ]
    if changes.get("compared"):
        lines.append("### Changes since the previous snapshot")
        for entity in ("buildings", "units", "commutes", "risks"):
            added, removed = changes[entity]["added"], changes[entity]["removed"]
            lines.append(f"- {entity}: +{len(added)} / -{len(removed)}")
        for p in changes["price_changes"]:
            lines.append(
                f"- unit {p['unit_id']}: rent {money(p['base_rent_before'])} -> "
                f"{money(p['base_rent_after'])}, fees {money(p['mandatory_fees_before'])} -> "
                f"{money(p['mandatory_fees_after'])}"
            )
    else:
        lines.append("_No previous snapshot to compare with._")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
