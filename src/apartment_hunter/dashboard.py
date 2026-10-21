"""Streamlit UI; all writes go through the same validated service as the CLI."""

import json
from datetime import timedelta
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from apartment_hunter.config import FACTORS, preferences, today
from apartment_hunter.db import database, scalar_schema
from apartment_hunter.exporting import csv_bytes, workbook_bytes
from apartment_hunter.outreach import inquiry
from apartment_hunter.schemas import CONTACT_STATUSES, SCHEMAS
from apartment_hunter.scoring import rank_all
from apartment_hunter.services import (
    followups,
    import_csv,
    research_queue,
    rows,
    save,
    serializable,
    stale,
)

st.set_page_config(page_title="December · NYC Apartment Search", page_icon="🏙️", layout="wide")
st.markdown(
    """<style>
.stApp { background: #f6f8f7; }
h1,h2,h3 { color: #173c4a; }
div[data-testid="stMetric"] { background: white; padding: 18px; border-radius: 12px;
border-top: 3px solid #368e80; }
</style>""",
    unsafe_allow_html=True,
)


def table(records: list[dict]) -> None:
    if not records:
        st.info("No records yet. Add evidence in Add / edit, or import a CSV.")
        return
    data = pd.DataFrame(serializable(records))
    for column in data.columns:
        if data[column].map(lambda v: isinstance(v, (list, dict))).any():
            data[column] = data[column].map(
                lambda v: json.dumps(v) if isinstance(v, (list, dict)) else v
            )
    st.dataframe(data, hide_index=True, use_container_width=True)


def edit_form(conn) -> None:
    entity = st.selectbox("Record type", list(SCHEMAS), key="edit_entity")
    records = rows(conn, entity)
    options = {0: "Create new"}
    options.update(
        {
            r[
                "id"
            ]: f"#{r['id']} · {r.get('name') or r.get('unit_number') or r.get('summary') or entity}"
            for r in records
        }
    )
    selected = st.selectbox("Record", list(options), format_func=options.get)
    existing = next((r for r in records if r["id"] == selected), None)
    schema = SCHEMAS[entity]
    st.caption(
        "Blank = unknown. Zero fees means explicitly confirmed zero. Dates use YYYY-MM-DD. "
        "Scores are your evidence-backed assessments, not automated review scores."
    )
    if entity != "buildings":
        with st.expander("Reference IDs"):
            for related in ("buildings", "units", "contacts"):
                st.write(related.title())
                table(
                    [
                        {k: r.get(k) for k in ("id", "name", "unit_number", "building_id")}
                        for r in rows(conn, related)
                    ]
                )
    with st.form(f"edit_{entity}_{selected}"):
        payload = {}
        columns = st.columns(3)
        for index, (field, prop) in enumerate(schema.model_json_schema()["properties"].items()):
            spec = scalar_schema(prop)
            default = existing[field] if existing else prop.get("default")
            label = field.replace("_", " ").title()
            if schema.model_fields[field].is_required():
                label += " *"
            key = f"{entity}_{selected}_{field}"
            with columns[index % 3]:
                enums = spec.get("enum")
                if entity == "contacts" and field == "status":
                    enums = list(CONTACT_STATUSES)
                if enums:
                    choices = ([None] if "anyOf" in prop else []) + enums
                    payload[field] = st.selectbox(
                        label,
                        choices,
                        index=choices.index(default) if default in choices else 0,
                        format_func=lambda x: "Unknown" if x is None else str(x),
                        key=key,
                    )
                elif spec.get("type") == "boolean":
                    choices = [None, True, False] if "anyOf" in prop else [False, True]
                    payload[field] = st.selectbox(
                        label,
                        choices,
                        index=choices.index(default) if default in choices else 0,
                        format_func=lambda x: "Unknown" if x is None else "Yes" if x else "No",
                        key=key,
                    )
                else:
                    value = st.text_input(
                        label,
                        value="" if default is None else str(default),
                        key=key,
                        help=prop.get("description"),
                    )
                    payload[field] = value.strip() or None
        submitted = st.form_submit_button("Save record", type="primary")
    if submitted:
        try:
            with conn.begin_nested():
                record_id = save(
                    conn,
                    entity,
                    payload,
                    selected or None,
                    existing["revision"] if existing else None,
                )
            st.success(f"Saved {entity} #{record_id}. Open another view to see the updated record.")
        except Exception as exc:
            st.error(str(exc))


def main() -> None:
    config = preferences()
    st.sidebar.title("December in NYC")
    st.sidebar.caption("Your shared apartment shortlist")
    page = st.sidebar.radio(
        "Workspace",
        [
            "Overview",
            "Buildings",
            "Property explorer",
            "Compare",
            "Map",
            "Contacts & tours",
            "Research queue",
            "Add / edit",
            "Import & export",
        ],
    )
    scenario = st.sidebar.selectbox(
        "Ranking scenario",
        ["Overall", "Value", "Commute", "Building quality", "Amenities", "Both occupants"],
    )
    scenario_factor = {
        "Value": "cost",
        "Commute": "commute",
        "Building quality": "condition",
        "Amenities": "amenities",
    }
    weights = dict(config.weights)
    if scenario in scenario_factor:
        weights[scenario_factor[scenario]] *= 2
    with st.sidebar.expander("Adjust scoring weights"):
        weights = {
            k: st.number_input(
                k.title(), min_value=0.0, value=float(weights[k]), key=f"weight_{scenario}_{k}"
            )
            for k in FACTORS
        }
    if sum(weights.values()) <= 0:
        st.error("At least one scoring weight must be positive.")
        return
    config = config.model_copy(update={"weights": weights})
    st.sidebar.caption(
        "Weight changes apply to this dashboard session. "
        "Edit config/preferences.toml to persist defaults."
    )
    st.title(page)
    st.caption(
        f"December 2026 · Up to ${config.budget:,.0f}/month including mandatory fees "
        "· 55 Hudson Yards"
    )
    with database() as conn:
        buildings, units = rows(conn, "buildings"), rows(conn, "units")
        ranked = rank_all(conn, config)
        if any(b["name"].startswith("SYNTHETIC") for b in buildings):
            st.warning(
                "DEMONSTRATION DATABASE — synthetic apartments, prices and commute estimates."
            )
        if scenario == "Both occupants":
            order = {"eligible": 0, "needs_verification": 1, "excluded": 2}
            ranked.sort(
                key=lambda r: (
                    order[r["eligibility"]],
                    -(r["both_score"] if r["both_score"] is not None else -1),
                )
            )
        if page == "Overview":
            metrics = st.columns(4)
            for col, label, value in zip(
                metrics,
                ("Building leads", "Listed units", "Eligible", "Due follow-ups"),
                (
                    len(buildings),
                    sum(u["status"] == "listed" for u in units),
                    sum(r["eligibility"] == "eligible" for r in ranked),
                    len(followups(conn)),
                ),
                strict=True,
            ):
                col.metric(label, value)
            st.info(
                "A building lead is not a December offer. Eligible means recorded evidence "
                "supports all hard constraints. Scores are provisional preference aids; "
                "completeness is shown separately."
            )
            recent = today() - timedelta(days=7)
            history = rows(conn, "price_history")
            reductions = 0
            for unit in units:
                observations = sorted(
                    [p for p in history if p["unit_id"] == unit["id"]], key=lambda p: p["id"]
                )
                if len(observations) >= 2:
                    last, prior = observations[-1], observations[-2]
                    reductions += bool(
                        last["base_rent"] is not None
                        and prior["base_rent"] is not None
                        and last["base_rent"] < prior["base_rent"]
                    )
            table(
                [
                    {
                        "Under budget (known fees)": sum(
                            r["gross_monthly_cost"] is not None
                            and r["gross_monthly_cost"] <= config.budget
                            for r in ranked
                        ),
                        "Within commute limit": sum(
                            r["commute_minutes"] is not None
                            and r["commute_minutes"] <= config.max_commute
                            for r in ranked
                        ),
                        "Discovered in last 7 days": sum(
                            u["created_at"][:10] >= str(recent) for u in units
                        ),
                        "Latest price reduced": reductions,
                        "Buildings needing research": sum(
                            b["pest_status"] == "unknown" or stale(b, 30) for b in buildings
                        ),
                        "Awaiting response": sum(
                            c["status"] == "awaiting_response" for c in rows(conn, "contacts")
                        ),
                    }
                ]
            )
            st.subheader("Next research steps")
            table(research_queue(conn)[:12])
        elif page == "Buildings":
            search = st.text_input("Search building or neighborhood")
            table(
                [
                    b
                    for b in buildings
                    if search.casefold() in f"{b['name']} {b['neighborhood']}".casefold()
                ]
            )
            st.caption(
                "Open Add / edit to record an address, leasing website, amenities, "
                "evidence or findings."
            )
        elif page == "Property explorer":
            search = st.text_input("Search building, neighborhood or amenities")
            statuses = st.multiselect(
                "Eligibility",
                ["eligible", "needs_verification", "excluded"],
                default=["eligible", "needs_verification"],
            )
            max_rent = st.number_input(
                "Maximum known monthly cost", value=float(config.budget), min_value=0.0
            )
            include_unknown = st.checkbox("Include unknown monthly costs", value=True)
            filtered = [
                r
                for r in ranked
                if r["eligibility"] in statuses
                and search.casefold()
                in f"{r['building']} {r['neighborhood']} {r['amenities']}".casefold()
                and (
                    (r["gross_monthly_cost"] is None and include_unknown)
                    or (r["gross_monthly_cost"] is not None and r["gross_monthly_cost"] <= max_rent)
                )
            ]
            table(filtered)
            st.caption(
                "Click column headings to sort. Unknown factors contribute zero evidence points; "
                "a low-completeness score is not an estimate of poor property quality."
            )
        elif page == "Compare":
            options = {r["unit_id"]: f"{r['building']} · {r['unit']}" for r in ranked}
            selected = st.multiselect("Choose apartments", list(options), format_func=options.get)
            chosen = [r for r in ranked if r["unit_id"] in selected]
            if chosen:
                frame = pd.DataFrame(
                    [
                        {
                            k: json.dumps(v) if isinstance(v, (dict, list)) else v
                            for k, v in r.items()
                        }
                        for r in chosen
                    ]
                )
                st.dataframe(frame.set_index("unit").T, use_container_width=True)
            else:
                st.info("Add units first, then choose two or more to compare.")
        elif page == "Map":
            geo = [b for b in buildings if b["latitude"] is not None and b["longitude"] is not None]
            st.caption(
                "Only entered coordinates are plotted. Approximate coordinates are not verified. "
                "Map tiles require internet; no automatic geocoding "
                "or transit-station data is loaded."
            )
            if geo:
                st.map(pd.DataFrame(geo), latitude="latitude", longitude="longitude")
                table(
                    [
                        {k: b[k] for k in ("name", "latitude", "longitude", "geocoding_status")}
                        for b in geo
                    ]
                )
            else:
                st.info("No sourced coordinates yet. Enter coordinates or open a route link below.")
            for b in buildings:
                if b["address"]:
                    query = urlencode(
                        {
                            "api": 1,
                            "origin": f"{b['address']}, {b['municipality']}, {b['state']}",
                            "destination": config.destination,
                            "travelmode": "transit",
                        }
                    )
                    st.link_button(
                        f"{b['name']} → office", f"https://www.google.com/maps/dir/?{query}"
                    )
        elif page == "Contacts & tours":
            st.subheader("Due follow-ups")
            table(followups(conn))
            st.subheader("Contact pipeline")
            table(rows(conn, "contacts"))
            st.subheader("Tours")
            table(rows(conn, "tours"))
            st.subheader("Interaction log")
            table(rows(conn, "interactions"))
            if buildings:
                names = {b["id"]: b["name"] for b in buildings}
                selected = st.selectbox("Draft an inquiry for", list(names), format_func=names.get)
                building = next(b for b in buildings if b["id"] == selected)
                draft = st.text_area(
                    "Editable draft — nothing is sent",
                    inquiry(building),
                    height=360,
                    key=f"draft_{selected}",
                )
                st.download_button("Download draft", draft, "leasing-inquiry.txt", "text/plain")
        elif page == "Research queue":
            table(research_queue(conn))
            st.subheader("Evidence and risk records")
            table(rows(conn, "risks"))
            st.subheader("Manual tasks")
            table(rows(conn, "tasks"))
        elif page == "Add / edit":
            edit_form(conn)
        elif page == "Import & export":
            st.subheader("Import reviewed records")
            entity = st.selectbox("CSV entity", list(SCHEMAS))
            st.download_button(
                "Download CSV header template",
                csv_bytes([], list(SCHEMAS[entity].model_fields)),
                f"{entity}-template.csv",
                "text/csv",
            )
            st.caption(
                "Use only the columns you need. Blank optional values mean unknown; "
                "omit columns to keep defaults. "
                "Updates require id and revision. The entire batch rolls back on error."
            )
            uploaded = st.file_uploader("CSV file", type="csv")
            if st.button("Validate and import", disabled=uploaded is None):
                try:
                    count = import_csv(conn, entity, uploaded.getvalue().decode("utf-8-sig"))
                    st.success(f"Imported {count} changes")
                except Exception as exc:
                    st.error(str(exc))
            st.subheader("Export a snapshot")
            st.caption(
                "Workbook uses saved configuration weights. "
                "Session scenario changes are reflected in the rankings CSV."
            )
            st.download_button(
                "Download Excel workbook",
                workbook_bytes(conn),
                "apartment-search.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            st.download_button(
                "Download rankings CSV", csv_bytes(ranked), "rankings.csv", "text/csv"
            )
            st.download_button(
                "Download editable entity CSV",
                csv_bytes(rows(conn, entity), ["id", "revision", *SCHEMAS[entity].model_fields]),
                f"{entity}.csv",
                "text/csv",
            )


main()
