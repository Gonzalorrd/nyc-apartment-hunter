from datetime import date
from email.message import EmailMessage

from apartment_hunter.services import rows, save
from apartment_hunter.streeteasy import email_listings, import_folder, read_email

ALERT = """Subject: 3 Results for Queens - 10/23/26
Date: 2026-10-23T19:57:27Z
Message-Id: test-alert

 Saved search update
NEW
 1 home new to market
 Rental Unit in Hunters Point
1 Example Street #7B
 $3,400 base rent
2 Open Houses
 Update:
Open House
 1 Bed
 1 Bath
 Example Realty (1 Main Street, Brooklyn, NY 11211)
<https://streeteasy.com/rental/1001>
UPDATED
 Rental Unit in Hunters Point
1 Example Street #7C
 $3,500 base rent
Open House Rented
 Updates:
Open House Rented 10/23/26
 1 Bed
 1 Bath
 Example Realty (1 Main Street, Brooklyn, NY 11211)
<https://streeteasy.com/rental/1002>
 Coop in Ditmars-Steinway
21-01 30th Street #4H
 $3,100 total monthly price
 2 Beds
 1 Bath
 Someone, LREB (521 5th Avenue, New York, NY 10175)
<https://streeteasy.com/rental/1003>
Because you searched for Financial District
 Rental Unit in Bayonne
130 Avenue F #542
 $3,100 base rent
 2 Beds
<https://streeteasy.com/rental/1004>
"""

SAVED = """Subject: Updates to Your Saved Listings - 10/22/26
Date: 2026-10-23T01:36:14Z
Message-Id: test-saved

Saved listing update
 Price Drop — saved September 23, 2026 <https://streeteasy.com/nyc/lists>
 <https://streeteasy.com/rental/2001>
 Condo unit in Hunters Point
2 Sample Avenue #12C
 $3,600 base rent
↓ $200
 1 bd|1 Bath|578 ft²
 Listed by Example Inc (369 Lexington Avenue, New York, NY 10017)
<https://streeteasy.com/rental/2001>
View all saved listings <https://streeteasy.com/nyc/lists>
"""

DELISTED = """Subject: Updates to 98-01 Queens Boulevard #3L
Date: 2026-10-20T14:43:35Z
Message-Id: test-delisted

 Listing Update
Important Update to Your Saved Listing - Recently De Listed:
 <https://streeteasy.com/rental/3001>
 RENTAL IN REGO PARK
 98-01 Queens Boulevard #3L <https://streeteasy.com/rental/3001>
 $3,950 total monthly price
 1 Bed
 1 Bath
 Listing by Modern Example (47 Vernon Boulevard, Long Island City, NY 11101)
 <https://streeteasy.com/rental/3001>
A Similar Laundry in Building Home
> <https://streeteasy.com/rental/3003?showcase=1>
 RENTAL IN ASTORIA Sponsored
 4-01 26th Avenue #404 <https://streeteasy.com/rental/3003?showcase=1>
 $3,866 base rent
 1 Bed
More Listings You Might Like
 Rental in Rego Park
 97-12 65 Road #17B
 $3,825 base rent
<https://streeteasy.com/rental/3002>
"""


def body(text):
    return text.split("\n\n", 1)[1]


def test_alert_listings_skip_recommendations_and_read_status():
    found = email_listings(body(ALERT))
    assert [f["title"] for f in found] == [
        "1 Example Street #7B",
        "1 Example Street #7C",
        "21-01 30th Street #4H",
    ]
    assert [f["status"] for f in found] == [None, "rented", None]
    assert found[0]["rent"] == 3400 and found[0]["broker"] == "Example Realty"
    assert found[0]["url"] == "https://streeteasy.com/rental/1001"
    assert found[1]["update"] == "Open House Rented 10/23/26"
    assert found[2]["rent_kind"] == "total" and found[2]["bedrooms"] == 2


def test_saved_listing_and_delisted_formats():
    (saved,) = email_listings(body(SAVED))
    assert saved["price_drop"] == 200 and saved["square_feet"] == 578
    assert saved["bedrooms"] == 1 and saved["broker"] == "Example Inc"
    (gone,) = email_listings(body(DELISTED))
    assert gone["status"] == "delisted" and gone["neighborhood"] == "Rego Park"
    assert gone["rent_kind"] == "total" and gone["broker"] == "Modern Example"


def test_eml_files_are_read(tmp_path):
    message = EmailMessage()
    message["Subject"] = "3 Results for Queens - 10/23/26"
    message["From"] = "noreply@email.streeteasy.com"
    message["Date"] = "Fri, 23 Oct 2026 19:57:27 +0000"
    message.set_content(body(ALERT))
    path = tmp_path / "alert.eml"
    path.write_bytes(bytes(message))
    subject, text, sent = read_email(path)
    assert subject.startswith("3 Results") and sent == date(2026, 10, 23)
    assert len(email_listings(text)) == 3


def test_email_import_adds_updates_and_skips(conn, tmp_path):
    emails = tmp_path / "streeteasy" / "emails"
    emails.mkdir(parents=True)
    for name, text in (("alert.txt", ALERT), ("saved.txt", SAVED), ("gone.txt", DELISTED)):
        (emails / name).write_text(text, encoding="utf-8")
    older = {
        "verified_on": date(2026, 10, 20),
        "verification": "source_checked",
        "source_notes": "Earlier check",
    }
    house = save(
        conn,
        "buildings",
        {"name": "Example House", "address": "1 Example Street", "municipality": "Queens"},
    )
    tower = save(
        conn,
        "buildings",
        {"name": "Sample Tower", "address": "2 Sample Avenue", "municipality": "Queens"},
    )
    rented = save(
        conn,
        "units",
        {"building_id": house, "unit_number": "7C", "base_rent": 3500, "status": "listed", **older},
    )
    cheaper = save(
        conn,
        "units",
        {
            "building_id": tower,
            "unit_number": "12C",
            "base_rent": 3800,
            "status": "listed",
            **older,
        },
    )

    preview = import_folder(conn, tmp_path / "streeteasy")
    assert preview["emails"] == 3 and preview["new_buildings"] == ["21-01 30th Street"]
    assert sorted(preview["new_units"]) == [
        "21-01 30th Street #4H: $3,100, 2 bed",
        "Example House #7B: $3,400, 1 bed",
    ]
    assert any("1 Example Street #7C: marked leased" in u for u in preview["updated_units"])
    assert any("2 Sample Avenue #12C: rent $3,600" in u for u in preview["updated_units"])
    assert any(s.startswith("98-01 Queens Boulevard #3L: delisted") for s in preview["skipped"])

    import_folder(conn, tmp_path / "streeteasy", apply=True)
    units = {u["id"]: u for u in rows(conn, "units")}
    assert units[rented]["status"] == "leased" and units[rented]["verified_on"] == date(
        2026, 10, 23
    )
    assert units[cheaper]["base_rent"] == 3600 and units[cheaper]["verified_on"] == date(
        2026, 10, 22
    )
    assert "Earlier check" in units[cheaper]["source_notes"]
    coop = next(u for u in units.values() if u["unit_number"] == "4H")
    assert coop["mandatory_fees"] == 0 and coop["base_rent"] == 3100  # Total monthly price.
    building = next(b for b in rows(conn, "buildings") if b["name"] == "21-01 30th Street")
    assert building["municipality"] == "Queens" and building["neighborhood"] == "Ditmars-Steinway"

    again = import_folder(conn, tmp_path / "streeteasy", apply=True)
    assert again["applied"] == {"buildings": 0, "units": 0, "updates": 0}


IN_CONTRACT = """Subject: In Contract: 5 Example Avenue #6E
Date: 2026-10-23T13:46:35Z
Message-Id: test-contract

Saved listing update
 In Contract — saved September 29, 2026 <https://streeteasy.com/nyc/lists>
<https://streeteasy.com/rental/4001>
In contract
 Condo unit in South Harlem
5 Example Avenue #6E
 $3,500 base rent
 1 bd|1 Bath
 Listed by Example Brokers (590 Madison Avenue, New York, NY 10022)
<https://streeteasy.com/rental/4001>
"""


def test_in_contract_listing_is_skipped_or_marked_unavailable(conn, tmp_path):
    folder = tmp_path / "streeteasy"
    folder.mkdir()
    (folder / "contract.txt").write_text(IN_CONTRACT, encoding="utf-8")
    (listing,) = email_listings(body(IN_CONTRACT))
    assert listing["status"] == "in contract"
    preview = import_folder(conn, folder)
    assert preview["skipped"] == ["5 Example Avenue #6E: in contract per StreetEasy (2026-10-23)"]

    building = save(
        conn,
        "buildings",
        {"name": "Example Condo", "address": "5 Example Avenue", "municipality": "Manhattan"},
    )
    unit = save(
        conn,
        "units",
        {
            "building_id": building,
            "unit_number": "6E",
            "base_rent": 3500,
            "status": "listed",
            "verification": "source_checked",
            "verified_on": date(2026, 10, 16),
            "source_notes": "Saved",
        },
    )
    import_folder(conn, folder, apply=True)
    assert next(u for u in rows(conn, "units") if u["id"] == unit)["status"] == "unavailable"
