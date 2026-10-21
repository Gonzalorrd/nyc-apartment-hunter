import json
from pathlib import Path

from apartment_hunter.config import today
from apartment_hunter.demo import load_demo
from apartment_hunter.publishing import write_snapshot
from apartment_hunter.services import save
from apartment_hunter.share_pipeline import (
    snapshot_changes,
    step_enrich,
    step_transform,
    step_validate,
)
from apartment_hunter.share_render import checked, money, step_render, step_report

EVIDENCE = {"source_url": "https://example.com", "verified_on": today()}


def lookup(query):
    if query.startswith("1 Main Street"):
        return "1 MAIN ST, HOBOKEN, NJ, 07030", 40.74, -74.03
    return None


def build(conn, tmp_path):
    snapshot = write_snapshot(conn, tmp_path / "snapshot.json")
    data, public = tmp_path / "_data", tmp_path / "public"
    step_validate(snapshot, data / "validation.json")
    step_enrich(
        snapshot, tmp_path / "cache.json", data / "points.json", data / "enrich.json", None, lookup
    )
    step_transform(snapshot, data / "points.json", data)
    step_render(data, tmp_path / "_output", public, Path("share"))
    return data, public


def test_buildings_only_site_shows_leads_and_hides_unit_charts(conn, tmp_path):
    save(
        conn,
        "buildings",
        {
            "name": "Mapped Lead",
            "address": "1 Main Street",
            "state": "NJ",
            "municipality": "Hoboken",
            "verification": "source_checked",
            **EVIDENCE,
        },
    )
    save(conn, "buildings", {"name": "Address Unknown", "neighborhood": "Woodside"})
    _, public = build(conn, tmp_path)
    page = (public / "index.html").read_text(encoding="utf-8")
    assert "No specific apartments are published yet" in page
    assert "Mapped Lead" in page and "Address Unknown" in page
    assert "Not checked yet" in page and "not on the map" in page
    assert "Cost vs. commute" not in page and "Monthly cost per apartment" not in page
    assert (public / ".nojekyll").exists()
    assert "nan" not in (public / "buildings.csv").read_text(encoding="utf-8-sig")
    units_csv = (public / "units.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len(units_csv) == 1 and units_csv[0].startswith("building,neighborhood,unit")
    empty_chart = (tmp_path / "_output" / "cost_vs_commute.html").read_text(encoding="utf-8")
    assert "No published unit" in empty_chart


def test_unit_site_escapes_html_and_contains_no_private_data(conn, tmp_path):
    load_demo(conn)
    save(conn, "buildings", {"name": "<script>alert(1)</script>"})
    save(
        conn, "contacts", {"building_id": 1, "notes": "Agent said we can haggle", "email": "a@b.co"}
    )
    data, public = build(conn, tmp_path)
    page = (public / "index.html").read_text(encoding="utf-8")
    exported = page + "".join(
        (public / name).read_text(encoding="utf-8-sig") for name in ("buildings.csv", "units.csv")
    )
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    for private in ("haggle", "a@b.co", "SYNTHETIC test fixture", "SYNTHETIC interaction"):
        assert private not in exported
    assert "Apartments" in page and "a month, all-in" in page
    assert "girlfriend" not in page.casefold()
    summary = json.loads((data / "summary.json").read_text(encoding="utf-8"))
    assert summary["units"] == 2


def test_display_formatting_never_shows_unknown_as_zero():
    assert money(3600) == "$3,600" and money(3600.5) == "$3,600.50"
    assert money(None) == "—" and money(float("nan")) == "—"
    assert checked(0) == "Checked today" and checked(1) == "Checked 1 day ago"
    assert checked(9.0) == "Checked 9 days ago" and checked(None) == "Not checked yet"


def test_run_report_lists_steps_and_changes(conn, tmp_path):
    load_demo(conn)
    data, _ = build(conn, tmp_path)
    current = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    previous = {**current, "buildings": [], "units": current["units"][:1]}
    step_report(data, snapshot_changes(previous, current), data / "run_summary.md")
    report = (data / "run_summary.md").read_text(encoding="utf-8")
    assert "| Validate | 1 buildings, 2 units" in report
    assert "- buildings: +1 / -0" in report and "- units: +1 / -0" in report
    step_report(data, snapshot_changes(None, current), data / "run_summary.md")
    assert "No previous snapshot" in (data / "run_summary.md").read_text(encoding="utf-8")
