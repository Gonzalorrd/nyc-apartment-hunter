import json

from apartment_hunter.config import Preferences
from apartment_hunter.scoring import effective_rent, rank_unit
from apartment_hunter.services import rows, save
from apartment_hunter.streeteasy import (
    building_name,
    cards,
    import_folder,
    listings,
    search_filters,
)


def apartment(url, title, street, zip_code, rent, beds=1, **extra):
    return {
        "@type": "Apartment",
        "@id": url,
        "url": url,
        "name": title,
        "numberOfBedrooms": beds,
        "numberOfBathroomsTotal": 1,
        "address": {
            "@type": "PostalAddress",
            "streetAddress": street,
            "addressLocality": "Hunters Point",
            "addressRegion": "NY",
            "postalCode": zip_code,
        },
        "geo": {"@type": "GeoCoordinates", "latitude": 40.75, "longitude": -73.94},
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "Monthly Rent", "value": f"${rent:,}/mo"},
            {"@type": "PropertyValue", "name": "Building Type", "value": "RENTAL"},
        ],
        **extra,
    }


NEW = "https://streeteasy.com/building/example-lic/5a"
KNOWN = "https://streeteasy.com/building/2_sample-avenue-sunnyside/2"
GONE = "https://streeteasy.com/building/gone-tower/9"
GRAPH = [
    apartment(NEW, "1 Example Street #5A", "1 Example Street", "11101", 4000),
    apartment(NEW, "1 Example Street #5A", "1 Example Street", "11101", 4000),  # Featured repeat.
    apartment(
        KNOWN,
        "2 Sample Avenue #2",
        "2 Sample Avenue",
        "11104",
        3300,
        beds=2,
        floorSize={"@type": "QuantitativeValue", "value": 640, "unitCode": "SQF"},
    ),
    apartment(GONE, "9 Gone Place #9", "9 Gone Place", "11377", 3500),
    {"@type": "Event", "url": NEW, "name": "Rental open house at 1 Example Street #5A"},
]


def card(title, *parts):
    spans = "".join(f"<span>{p}</span>" for p in parts)
    return (
        '<div data-testid="listing-card" role="presentation"><p>Rental unit</p>'
        f"<p>in Hunters Point</p><a>{title}</a>{spans}</div>"
    )


PAGE = (
    '<html><head><script type="application/ld+json">'
    + json.dumps({"@context": "https://schema.org", "@graph": GRAPH})
    + "</script></head><body>"
    '<a href="https://streeteasy.com/for-rent/nyc/status:open%7Cprice:3000-4000%7C'
    'available_after:20261201?sort_by=se_score&amp;page=2">2</a>'
    + card(
        "1 Example Street #5A",
        "$4,000",
        "base rent",
        "$3,750",
        "net effective base rent",
        "1",
        "month free",
        "–",
        "16",
        "-month lease",
        "Missing:",
        "Washer/dryer",
        "Listing by",
        "Example Realty",
        "Open:",
        "Oct 25",
        "(",
        "10",
        "AM",
        "–",
        "5",
        "PM",
        ")",
    )
    + card("2 Sample Avenue #2", "$3,300", "base rent", "Amenities match", "Listing by", "Owner")
    + "</body></html>"
)


def save_page(tmp_path, name="Long search title _ StreetEasy.htm"):
    folder = tmp_path / "streeteasy"
    folder.mkdir()
    (folder / name).write_text(PAGE, encoding="utf-8")
    return folder


def test_parses_unique_apartments_cards_and_search():
    found = listings(PAGE)
    assert [f["title"] for f in found] == [
        "1 Example Street #5A",
        "2 Sample Avenue #2",
        "9 Gone Place #9",
    ]
    assert (
        found[0]["rent"] == 4000 and found[0]["unit"] == "5A" and found[0]["slug"] == "example-lic"
    )
    assert found[1]["square_feet"] == 640 and found[1]["bedrooms"] == 2
    details = cards(PAGE)["1 Example Street #5A"]
    assert details["net_effective"] == 3750 and details["months_free"] == 1
    assert details["lease_months"] == 16 and details["broker"] == "Example Realty"
    assert details["missing"] == "Washer/dryer" and details["open_house"].startswith(
        "Oct 25 (10 AM"
    )
    assert search_filters(PAGE) == "nyc/status:open|price:3000-4000|available_after:20261201"


def test_building_names_from_slugs():
    assert building_name("bevel-lic", "42-22 27th Street") == "Bevel LIC"
    assert building_name("42_20-27-street-long_island_city", "42-20 27th Street") == (
        "42-20 27th Street"
    )


def test_import_matches_known_buildings_skips_dropped_and_is_repeatable(conn, tmp_path):
    folder = save_page(tmp_path)
    known = save(
        conn,
        "buildings",
        {"name": "Sample Tower", "address": "2 Sample Avenue", "municipality": "Queens"},
    )
    save(
        conn,
        "buildings",
        {
            "name": "Gone Tower",
            "address": "9 Gone Place",
            "municipality": "Queens",
            "household_status": "dropped",
        },
    )
    preview = import_folder(conn, folder)
    assert preview["new_buildings"] == ["Example LIC"]
    assert (
        len(preview["new_units"]) == 2
        and "9 Gone Place #9: Gone Tower was dropped" in preview["skipped"]
    )
    assert len(rows(conn, "buildings")) == 2 and not rows(conn, "units")  # Dry run.

    assert import_folder(conn, folder, apply=True)["applied"] == {
        "buildings": 1,
        "units": 2,
        "updates": 0,
    }
    by_number = {u["unit_number"]: u for u in rows(conn, "units")}
    assert by_number["2"]["building_id"] == known
    new_building = next(b for b in rows(conn, "buildings") if b["name"] == "Example LIC")
    assert new_building["municipality"] == "Queens" and new_building["reviewed_on"] is None
    assert new_building["latitude"] == 40.75
    unit = by_number["5A"]
    assert unit["base_rent"] == 4000 and unit["lease_months"] == 16
    assert effective_rent(unit) == 3750  # Matches StreetEasy's net-effective figure.
    assert unit["mandatory_fees"] is None and unit["listing_url"] == NEW
    assert "Example Realty" in unit["source_notes"] and "2026-12-01" in unit["source_notes"]

    again = import_folder(conn, folder, apply=True)
    assert again["applied"] == {"buildings": 0, "units": 0, "updates": 0}
    assert len(rows(conn, "units")) == 2


def test_two_bedrooms_count_as_candidates(conn, tmp_path):
    import_folder(conn, save_page(tmp_path), apply=True)
    two_bed = next(u for u in rows(conn, "units") if u["bedrooms"] == 2)
    building = next(b for b in rows(conn, "buildings") if b["id"] == two_bed["building_id"])
    result = rank_unit(two_bed, building, [], [], [], Preferences())
    assert "Separate bedroom" not in result["reasons"]


def test_one_building_page_with_two_addresses_becomes_one_building(conn, tmp_path):
    graph = [
        apartment(NEW, "1 Example Street #5A", "1 Example Street", "11101", 3500),
        apartment(NEW + "-b", "3 Example Street #5A", "3 Example Street", "11101", 3600),
    ]
    folder = tmp_path / "pages"
    folder.mkdir()
    (folder / "page.html").write_text(
        '<script type="application/ld+json">' + json.dumps({"@graph": graph}) + "</script>",
        encoding="utf-8",
    )
    result = import_folder(conn, folder, apply=True)
    assert result["new_buildings"] == ["Example LIC"]
    (building,) = rows(conn, "buildings")
    assert building["address"] == "1 Example Street / 3 Example Street"
    assert sorted(u["unit_number"] for u in rows(conn, "units")) == ["3-5A", "5A"]
