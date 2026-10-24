"""Import StreetEasy listings from pages and emails the user saved.

StreetEasy refuses automated requests, so the app never fetches it. Two inputs, both kept
in `data/imports/streeteasy/` (gitignored):

- Results pages saved from the browser (Ctrl+S, "Webpage, HTML only"): each page's
  schema.org JSON-LD "Apartment" records plus the visible listing-card text (net-effective
  price, free months, lease length).
- Alert emails saved as `.eml` or as plain text (`.txt`, optionally starting with
  "Subject:" and "Date:" lines): saved-search alerts and saved-listing updates. Their
  recommendation sections ("Because you searched for ...") are ignored.

Every listing sighting becomes an observation. The newest one per apartment wins: it adds
the apartment or updates one already in the app (price change, "Rented"). Saved files are
untrusted data: nothing in them is executed and only the listing fields below are kept.
"""

import email
import html as htmllib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email import policy
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from apartment_hunter.schemas import SCHEMAS
from apartment_hunter.services import normalize, rows, save

DEFAULT_FOLDER = Path("data/imports/streeteasy")
NEW_YORK = ZoneInfo("America/New_York")
JSON_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
CARD = 'data-testid="listing-card"'
SEARCH_LINK = re.compile(r"/for-rent/([^\"'?&\s<>]+)")
BUILDING_SLUG = re.compile(r"streeteasy\.com/building/([^/?#\"]+)")
RENTAL_URL = re.compile(r"https://streeteasy\.com/rental/(\d+)")
LISTING_TYPE = re.compile(
    r"^((?:rental|condo|co-?op|townhouse|house|multi-family)(?: unit)?) in (.+)$", re.I
)
ADDRESS = re.compile(r"^(.+?) #\s*([^<\s][^<]*?)\s*(?:<https?://\S+>)?$")
RECOMMENDATIONS = (
    "Because you searched for",
    "More Listings You Might Like",
    "See more similar listings",
    "You get this saved search email",
    "Get the StreetEasy App",
)
QUEENS_HOUSE_NUMBER = re.compile(r"^\d+-\d+\s")  # Queens addresses, e.g. "42-20 27th Street".
BOROUGH_BY_ZIP_PREFIX = {
    "100": "Manhattan",
    "101": "Manhattan",
    "102": "Manhattan",
    "103": "Staten Island",
    "104": "Bronx",
    "112": "Brooklyn",
    "110": "Queens",
    "111": "Queens",
    "113": "Queens",
    "114": "Queens",
    "116": "Queens",
}
NEIGHBORHOODS = {
    "Manhattan": (
        "battery park city",
        "carnegie hill",
        "central harlem",
        "chelsea",
        "chinatown",
        "civic center",
        "east harlem",
        "east village",
        "financial district",
        "flatiron",
        "gramercy",
        "gramercy park",
        "greenwich village",
        "hamilton heights",
        "harlem",
        "hell's kitchen",
        "hudson square",
        "hudson yards",
        "inwood",
        "kips bay",
        "lenox hill",
        "lincoln square",
        "little italy",
        "lower east side",
        "manhattan valley",
        "manhattanville",
        "midtown",
        "midtown east",
        "midtown west",
        "morningside heights",
        "murray hill",
        "noho",
        "nolita",
        "nomad",
        "roosevelt island",
        "soho",
        "south harlem",
        "stuyvesant town",
        "sutton place",
        "tribeca",
        "turtle bay",
        "two bridges",
        "upper east side",
        "upper west side",
        "washington heights",
        "west chelsea",
        "west harlem",
        "west village",
        "yorkville",
    ),
    "Brooklyn": (
        "bedford-stuyvesant",
        "boerum hill",
        "brooklyn heights",
        "bushwick",
        "carroll gardens",
        "clinton hill",
        "cobble hill",
        "crown heights",
        "downtown brooklyn",
        "dumbo",
        "east williamsburg",
        "flatbush",
        "fort greene",
        "gowanus",
        "greenpoint",
        "park slope",
        "prospect heights",
        "prospect lefferts gardens",
        "red hook",
        "williamsburg",
    ),
    "Queens": (
        "astoria",
        "ditmars-steinway",
        "elmhurst",
        "forest hills",
        "hunters point",
        "jackson heights",
        "long island city",
        "rego park",
        "ridgewood",
        "sunnyside",
        "woodside",
    ),
    "Bronx": ("concourse", "mott haven", "port morris", "riverdale"),
}
BOROUGH_BY_NEIGHBORHOOD = {n: b for b, names in NEIGHBORHOODS.items() for n in names}
NJ_PLACES = {
    "bayonne",
    "edgewater",
    "hoboken",
    "jersey city",
    "union city",
    "weehawken",
    "west new york",
}
UPPER_WORDS = {"lic", "nyc", "ues", "uws", "fidi"}


def long_path(path: Path) -> str:
    """Windows refuses paths over 260 characters unless they use the \\\\?\\ prefix, and saved
    StreetEasy pages are named after the whole search."""
    resolved = str(path.resolve())
    return "\\\\?\\" + resolved if os.name == "nt" and not resolved.startswith("\\\\") else resolved


def file_date(path: Path) -> date:
    return datetime.fromtimestamp(os.stat(long_path(path)).st_mtime, NEW_YORK).date()


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def saved_files(folder: Path, suffixes: tuple[str, ...]) -> list[Path]:
    """Files with these suffixes in `folder` and one level of subfolders (e.g. emails/)."""
    found = []
    for name in sorted(os.listdir(long_path(folder))):
        path = folder / name
        if os.path.isdir(long_path(path)):
            found.extend(
                path / child
                for child in sorted(os.listdir(long_path(path)))
                if child.lower().endswith(suffixes)
            )
        elif name.lower().endswith(suffixes):
            found.append(path)
    return found


def saved_pages(folder: Path) -> list[tuple[str, Path, date]]:
    """(text, path, New York date the page was saved), oldest first."""
    pages = [
        (decode(Path(long_path(path)).read_bytes()), path, file_date(path))
        for path in saved_files(folder, (".htm", ".html"))
    ]
    return sorted(pages, key=lambda page: (page[2], page[1].name))


def money(text) -> float | None:
    match = re.search(r"\$([\d,]+(?:\.\d{1,2})?)", str(text or ""))
    return float(match.group(1).replace(",", "")) if match else None


def quantity(value, unit_code: str) -> float | None:
    if isinstance(value, dict) and value.get("unitCode") == unit_code:
        try:
            return float(value["value"])
        except (KeyError, TypeError, ValueError):
            return None
    return None


def listings(page: str) -> list[dict]:
    """Unique JSON-LD apartments on a results page (featured listings repeat)."""
    found: dict[str, dict] = {}
    for block in JSON_LD.findall(page):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        for item in items if isinstance(items, list) else []:
            if (
                not isinstance(item, dict)
                or item.get("@type") != "Apartment"
                or not item.get("url")
            ):
                continue
            url = str(item["url"])
            if url in found or not BUILDING_SLUG.search(url):
                continue
            props = {
                p.get("name"): p.get("value")
                for p in item.get("additionalProperty", [])
                if isinstance(p, dict)
            }
            address = item.get("address") if isinstance(item.get("address"), dict) else {}
            geo = item.get("geo") if isinstance(item.get("geo"), dict) else {}
            street, _, unit = str(item.get("name") or "").partition(" #")
            found[url] = {
                "url": url,
                "title": str(item.get("name") or ""),
                "slug": BUILDING_SLUG.search(url).group(1),
                "street": address.get("streetAddress") or street,
                "unit": unit or url.rstrip("/").rsplit("/", 1)[-1],
                "neighborhood": address.get("addressLocality"),
                "state": address.get("addressRegion") or "NY",
                "zip_code": address.get("postalCode"),
                "latitude": geo.get("latitude"),
                "longitude": geo.get("longitude"),
                "bedrooms": item.get("numberOfBedrooms"),
                "bathrooms": item.get("numberOfBathroomsTotal"),
                "square_feet": quantity(item.get("floorSize"), "SQF"),
                "lease_months": quantity(item.get("leaseLength"), "MON"),
                "rent": money(props.get("Monthly Rent")),
                "rent_kind": "base",
                "building_type": props.get("Building Type"),
            }
    return list(found.values())


def cards(page: str) -> dict[str, dict]:
    """Visible listing-card details keyed by the card title, e.g. "1 Main Street #2A"."""
    details: dict[str, dict] = {}
    for chunk in page.split(CARD)[1:]:
        text = htmllib.unescape(re.sub(r"<[^>]+>", " | ", chunk[:20000]))
        text = re.sub(r"(\s*\|\s*)+", " | ", text)
        title = re.search(r"\| ([^|]+ #[^|]+?) \|", text)
        if not title or title.group(1).strip() in details:
            continue

        def find(pattern: str, text: str = text) -> str | None:
            match = re.search(pattern, text)
            return match.group(1).strip() if match else None

        opening = find(r"Open: \| (.+?) \| \)")
        details[title.group(1).strip()] = {
            "net_effective": money(find(r"(\$[\d,]+) \| net effective")),
            "months_free": float(find(r"([\d.]+) \| months? free") or 0) or None,
            "lease_months": float(find(r"(\d+) \| -month lease") or 0) or None,
            "broker": find(r"Listing by \| ([^|]+?) \|"),
            "open_house": re.sub(r"\s*\|\s*", " ", opening).replace("( ", "(") if opening else None,
            "missing": find(r"Missing: \| ([^|]+?) \|"),
        }
    return details


def search_filters(page: str) -> str | None:
    """The StreetEasy search the page came from, e.g. "nyc/status:open|price:3000-4000|...",
    read from the page's own pagination links."""
    for match in SEARCH_LINK.finditer(page):
        decoded = unquote(htmllib.unescape(match.group(1)))
        if "|" in decoded or ":" in decoded:
            return decoded
    return None


def page_observations(folder: Path) -> tuple[list[dict], list[str], int]:
    """(observations, search filters, number of pages read)."""
    observations, searches = [], []
    pages = saved_pages(folder)
    for page, _path, saved in pages:
        search = search_filters(page)
        if search and search not in searches:
            searches.append(search)
        moving = re.search(r"available_after:(\d{4})(\d{2})(\d{2})", search or "")
        details = cards(page)
        for item in listings(page):
            card = details.get(item["title"], {})
            observations.append(
                {
                    **item,
                    **{k: v for k, v in card.items() if v is not None},
                    "lease_months": card.get("lease_months") or item["lease_months"],
                    "source": "a saved StreetEasy search page",
                    "seen": saved,
                    "moving_after": "-".join(moving.groups()) if moving else None,
                    "status": None,
                }
            )
    return observations, searches, len(pages)


def read_email(path: Path) -> tuple[str, str, date]:
    """(subject, plain-text body, New York date) of a saved `.eml` or `.txt` email."""
    raw = Path(long_path(path)).read_bytes()
    if path.suffix.lower() == ".eml":
        message = email.message_from_bytes(raw, policy=policy.default)
        part = message.get_body(preferencelist=("plain", "html"))
        body = part.get_content() if part else ""
        if part and part.get_content_type() == "text/html":
            body = htmllib.unescape(re.sub(r"<[^>]+>", "\n", body))
        sent = message.get("Date")
        when = message["Date"].datetime.astimezone(NEW_YORK).date() if sent else file_date(path)
        return str(message.get("Subject") or ""), body, when
    text = decode(raw).replace("\r\n", "\n").replace("\r", "\n")  # Files saved on Windows.
    headers, _, body = text.partition("\n\n") if text.startswith("Subject:") else ("", "", text)
    fields = dict(
        line.split(":", 1) for line in headers.splitlines() if ":" in line and line[0].isalpha()
    )
    when = file_date(path)
    if fields.get("Date"):
        stamp = datetime.fromisoformat(fields["Date"].strip().replace("Z", "+00:00"))
        when = stamp.astimezone(NEW_YORK).date()
    return fields.get("Subject", "").strip(), body, when


def email_listings(body: str) -> list[dict]:
    """Listings in an alert email, before its recommendation section."""
    lines = [line.strip().replace("͏", "").strip() for line in body.splitlines()]
    cut = next((i for i, line in enumerate(lines) if line.startswith(RECOMMENDATIONS)), None)
    lines = lines[:cut]
    found, pending = [], None
    for i, line in enumerate(lines):
        if re.search(r"de ?listed", line, re.I):
            pending = "delisted"
        elif re.search(r"\bin contract\b", line, re.I):
            pending = "in contract"
        kind = LISTING_TYPE.match(line)
        if not kind:
            continue
        j = i + 1
        while j < len(lines) and (not lines[j] or lines[j].startswith("<")):
            j += 1
        address = ADDRESS.match(lines[j]) if j < len(lines) else None
        if not address:
            continue
        end = next((k for k in range(j + 1, len(lines)) if LISTING_TYPE.match(lines[k])), None)
        block = "\n".join(lines[j:end])
        url = RENTAL_URL.search(block)
        # "A Similar ... Home" ads: "RENTAL IN ASTORIA Sponsored", own link with showcase=1.
        own_link = re.search(r"https://streeteasy\.com/rental/\d+\S*", block)
        if not url or re.search(r"\bsponsored\b", line, re.I) or "showcase=" in own_link.group(0):
            continue
        price = re.search(r"\$([\d,]+)\s+(base rent|total monthly price)", block, re.I)
        free = re.search(r"([\d.]+) months? free\s*•\s*(\d+)-month lease", block)
        bed_count = re.search(r"(?m)^(\d+)\s*(?:Beds?|bd)\b", block)
        studio = re.search(r"(?m)^Studio\b", block)
        update = re.search(r"Updates?:\n(.+?)(?:\n\n|\n\d+ (?:Beds?|bd)\b|$)", block, re.S)
        broker = re.search(r"(?m)^(?:Listed by |Listing by )(.+?)(?:\s*\(|\s*<|$)", block) or (
            re.search(r"(?m)^([A-Z][^$\n]*?)\s*\([^)]*\d{5}(?:-\d{4})?\)", block)
        )
        status = "rented" if re.search(r"\bRented\b", block) else pending
        found.append(
            {
                "url": f"https://streeteasy.com/rental/{url.group(1)}",
                "title": f"{address.group(1).strip()} #{address.group(2).strip()}",
                "slug": None,
                "street": address.group(1).strip(),
                "unit": address.group(2).strip(),
                "neighborhood": kind.group(2).strip().title()
                if kind.group(2).isupper()
                else kind.group(2).strip(),
                "state": "NY",
                "zip_code": None,
                "latitude": None,
                "longitude": None,
                "bedrooms": 0
                if studio and not bed_count
                else int(bed_count.group(1))
                if bed_count
                else None,
                "bathrooms": float(m.group(1))
                if (m := re.search(r"([\d.]+)\s*Baths?\b", block))
                else None,
                "square_feet": float(m.group(1).replace(",", ""))
                if (m := re.search(r"([\d,]+)\s*ft²", block))
                else None,
                "rent": float(price.group(1).replace(",", "")) if price else None,
                "rent_kind": "total" if price and "total" in price.group(2).lower() else "base",
                "net_effective": money(m.group(0))
                if (m := re.search(r"\$[\d,]+\s+net effective", block))
                else None,
                "months_free": float(free.group(1)) if free else None,
                "lease_months": float(free.group(2)) if free else None,
                "broker": broker.group(1).strip() if broker else None,
                "update": " ".join(update.group(1).split()) if update else None,
                "price_drop": money(m.group(0))
                if (m := re.search(r"↓\s*\$[\d,]+", block))
                else None,
                "building_type": kind.group(1),
                "status": status,
            }
        )
        pending = None
    return found


def email_observations(folder: Path) -> tuple[list[dict], int]:
    """(observations, number of StreetEasy emails read)."""
    observations, count = [], 0
    for path in saved_files(folder, (".eml", ".txt")):
        subject, body, sent = read_email(path)
        if "streeteasy" not in body.casefold() and "streeteasy" not in subject.casefold():
            continue
        count += 1
        source = (
            "a StreetEasy saved-search alert"
            if re.search(r"\bResults? for\b", subject)
            else "a StreetEasy saved-listing update"
        )
        for item in email_listings(body):
            observations.append({**item, "source": f"{source} ({subject})", "seen": sent})
    return observations, count


def place_of(item: dict) -> tuple[str, str | None]:
    """(state, borough or NJ municipality) for building identity."""
    neighborhood = (item.get("neighborhood") or "").casefold()
    if neighborhood in NJ_PLACES:
        return "NJ", item["neighborhood"]
    if item.get("zip_code"):
        return item["state"], BOROUGH_BY_ZIP_PREFIX.get(item["zip_code"][:3])
    if QUEENS_HOUSE_NUMBER.match(item["street"]):
        return "NY", "Queens"
    return "NY", BOROUGH_BY_NEIGHBORHOOD.get(neighborhood)


def building_name(slug: str | None, street: str) -> str:
    """StreetEasy names unnamed buildings by address ("42_20-27-street-..."); use the street
    address for those and a title-cased slug otherwise ("bevel-lic" -> "Bevel LIC")."""
    if not slug or re.match(r"^\d+(_\d+)?-", slug):
        return street
    return " ".join(w.upper() if w in UPPER_WORDS else w.capitalize() for w in slug.split("-"))


def identity(street: str, place: str | None, state: str) -> str:
    """Same normalization as `services.save` uses for `identity_key`."""
    return normalize(f"{street}|{place}|{state}")


def latest(observations: list[dict]) -> list[dict]:
    """Newest observation per apartment (same street and unit), with gaps such as map
    coordinates filled from older sightings. Pages win ties: they carry more fields."""
    grouped: dict[str, list[dict]] = {}
    for item in observations:
        state, place = place_of(item)
        key = identity(item["street"], place, state) + "#" + item["unit"].upper().lstrip("#")
        grouped.setdefault(key, []).append(item)
    chosen = []
    for items in grouped.values():
        items.sort(key=lambda o: (o["seen"], o.get("slug") is not None))
        newest = dict(items[-1])
        for older in reversed(items[:-1]):
            for k, v in older.items():
                if newest.get(k) is None and v is not None and k not in ("status", "update"):
                    newest[k] = v
        chosen.append(newest)
    return sorted(chosen, key=lambda o: (o["seen"], o["title"]))


@dataclass
class Plan:
    pages: int = 0
    emails: int = 0
    searches: list[str] = field(default_factory=list)
    # New building payloads keyed by "slug:<StreetEasy building page>" or "addr:<identity>".
    # One building page can list several street addresses; they share one record.
    buildings: dict[str, dict] = field(default_factory=dict)
    units: list[tuple[str, dict]] = field(default_factory=list)  # (building key, payload).
    # (unit already in the app, field changes, note, date of the sighting).
    updates: list[tuple[dict, dict, str, date]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    existing: dict[str, int] = field(default_factory=dict)  # Building key -> existing id.

    def summary(self, names: dict[str, str]) -> dict:
        return {
            "pages": self.pages,
            "emails": self.emails,
            "searches": self.searches,
            "new_buildings": [b["name"] for b in self.buildings.values()],
            "new_units": [
                f"{names[key]} #{u['unit_number']}: "
                + (f"${u['base_rent']:,.0f}" if u["base_rent"] is not None else "rent unknown")
                + f", {u['bedrooms']} bed"
                for key, u in self.units
            ],
            "updated_units": [note for _, _, note, _ in self.updates],
            "skipped": self.skipped,
        }


def unit_notes(item: dict) -> str:
    rent, free, lease = item["rent"], item.get("months_free"), item.get("lease_months")
    notes = [
        f"From {item['source']}, {item['seen']}: {item['url']}.",
        "Rent not shown."
        if rent is None
        else f"Total monthly price ${rent:,.0f} (StreetEasy: includes required fees)."
        if item.get("rent_kind") == "total"
        else f"Base rent ${rent:,.0f}; StreetEasy says base rent excludes fees.",
        f"Net effective ${item['net_effective']:,.0f} with {free:g} month(s) free"
        + (f" on a {lease:g}-month lease." if lease else ".")
        if item.get("net_effective") and free
        else "",
        f"Price dropped ${item['price_drop']:,.0f}." if item.get("price_drop") else "",
        f"Listed by {item['broker']}." if item.get("broker") else "",
        f"Open house {item['open_house']}." if item.get("open_house") else "",
        f"Latest StreetEasy update: {item['update']}." if item.get("update") else "",
        f"Card says missing: {item['missing']}." if item.get("missing") else "",
        f"The search was filtered to move-in after {item['moving_after']}; exact date not shown."
        if item.get("moving_after")
        else "",
        "Bedroom count from StreetEasy; fees, December date and occupancy rules not confirmed.",
    ]
    return " ".join(n for n in notes if n)


def unit_payload(item: dict, unit_number: str) -> dict:
    rent, free, lease = item["rent"], item.get("months_free"), item.get("lease_months")
    bedrooms = item["bedrooms"]
    total = item.get("rent_kind") == "total"
    return {
        "unit_number": unit_number,
        "bedrooms": bedrooms,
        "separate_bedroom": True if bedrooms and bedrooms >= 1 else None,
        "bathrooms": item.get("bathrooms") or None,
        "square_feet": item.get("square_feet"),
        "advertised_rent": rent,
        "rent_basis": "gross" if rent is not None else "unknown",
        "base_rent": rent,
        # A "total monthly price" already includes required fees, so the all-in cost is right.
        "mandatory_fees": 0 if total and rent is not None else None,
        "concession_total": round(rent * free, 2) if rent and free and lease else None,
        "lease_months": int(lease) if lease else None,
        "status": "listed",
        "listing_url": item["url"],
        "source_url": item["url"],
        "source_notes": unit_notes(item),
        "verified_on": item["seen"],
        "verification": "source_checked",
    }


def plan_import(conn, folder: Path = DEFAULT_FOLDER) -> Plan:
    plan = Plan()
    buildings = rows(conn, "buildings")
    index: dict[str, dict] = {}
    for b in buildings:
        for street in (b["address"] or "").split(" / "):
            if street.strip():
                index[
                    identity(street.strip(), b["municipality"] or b["neighborhood"], b["state"])
                ] = b
        for url in (b["source_url"], b["listing_url"], b["website"]):
            for slug in BUILDING_SLUG.findall(url or ""):
                index.setdefault(f"slug:{slug}", b)
    units = rows(conn, "units")
    by_url = {u["listing_url"]: u for u in units if u["listing_url"]}
    by_number = {(u["building_id"], u["unit_number"]): u for u in units}
    new_index: dict[str, str] = {}  # Identity of a planned building's address -> building key.
    planned: set[tuple[str, str]] = set()

    page_items, plan.searches, plan.pages = page_observations(folder)
    mail_items, plan.emails = email_observations(folder)
    for item in latest(page_items + mail_items):
        state, place = place_of(item)
        key = identity(item["street"], place, state)
        match = index.get(key) or (item["slug"] and index.get(f"slug:{item['slug']}"))
        unit_number = item["unit"].upper().lstrip("#").strip()
        if match:
            if match["household_status"] == "dropped":
                plan.skipped.append(f"{item['title']}: {match['name']} was dropped")
                continue
            plan.existing[key] = match["id"]
            building_key, building_id = key, match["id"]
            known = by_url.get(item["url"]) or by_number.get((match["id"], unit_number))
        else:
            building_key = new_index.get(key) or (
                f"slug:{item['slug']}" if item["slug"] else f"addr:{key}"
            )
            building_id, known = None, by_url.get(item["url"])
        if known:
            plan_update(plan, known, item)
            continue
        if item["status"]:
            plan.skipped.append(
                f"{item['title']}: {item['status']} per StreetEasy ({item['seen']})"
            )
            continue
        if building_id is None:
            building = plan.buildings.get(building_key)
            if building and item["street"] not in building["address"].split(" / "):
                building["address"] += f" / {item['street']}"
            if not building:
                plan.buildings[building_key] = {
                    "name": building_name(item["slug"], item["street"]),
                    "address": item["street"],
                    "neighborhood": item["neighborhood"],
                    "municipality": place,
                    "state": state,
                    "zip_code": item.get("zip_code"),
                    "latitude": item.get("latitude"),
                    "longitude": item.get("longitude"),
                    "geocoding_status": "approximate" if item.get("latitude") else "unknown",
                    "source_url": f"https://streeteasy.com/building/{item['slug']}"
                    if item["slug"]
                    else item["url"],
                    "source_notes": f"Found via {item['source']} ({item['seen']}). Address "
                    "comes from the listing; building identity and condition not "
                    "independently checked.",
                    "verified_on": item["seen"],
                    "verification": "source_checked",
                }
            new_index[key] = building_key
        if (building_key, unit_number) in planned:  # Same unit number at another address.
            unit_number = f"{item['street'].split()[0]}-{unit_number}"
        planned.add((building_key, unit_number))
        payload = unit_payload(item, unit_number)
        if building_id is not None:
            payload["building_id"] = building_id
        plan.units.append((building_key, payload))
    return plan


def plan_update(plan: Plan, unit: dict, item: dict) -> None:
    """Apply a newer sighting of an apartment already in the app: "Rented" marks it leased,
    and a new price replaces the old one. Older or unchanged sightings are skipped."""
    label = item["title"]
    if unit["verified_on"] and item["seen"] < unit["verified_on"]:
        plan.skipped.append(f"{label}: already in the app with newer information")
        return
    if item["status"] == "delisted":
        plan.skipped.append(f"{label}: de-listed per StreetEasy ({item['seen']}); check it")
        return
    changes = {}
    if item["status"] == "rented" and unit["status"] != "leased":
        changes["status"] = "leased"
    if item["status"] == "in contract" and unit["status"] not in ("leased", "unavailable"):
        changes["status"] = "unavailable"
    rent = item["rent"]
    if rent is not None and item.get("rent_kind") != "total":
        current = float(unit["base_rent"]) if unit["base_rent"] is not None else None
        if current != rent:
            changes.update(base_rent=rent, advertised_rent=rent, rent_basis="gross")
    if not changes:
        plan.skipped.append(f"{label}: already in the app")
        return
    what = ", ".join(
        f"marked {changes['status']}" if k == "status" else f"rent ${rent:,.0f}"
        for k in changes
        if k in ("status", "base_rent")
    )
    note = f"{label}: {what} ({item['source']}, {item['seen']})"
    plan.updates.append((unit, changes, note, item["seen"]))


def apply_import(conn, plan: Plan) -> dict[str, int]:
    """Create new buildings, then units, then updates, through the validated `save`."""
    ids = dict(plan.existing)
    for key, payload in plan.buildings.items():
        ids[key] = save(conn, "buildings", payload)
    for key, payload in plan.units:
        save(conn, "units", {**payload, "building_id": payload.get("building_id") or ids[key]})
    fields = SCHEMAS["units"].model_fields
    for unit, changes, note, seen in plan.updates:
        current = next(u for u in rows(conn, "units") if u["id"] == unit["id"])
        payload = {k: current[k] for k in fields} | changes
        payload["verified_on"] = seen
        payload["source_notes"] = f"{current['source_notes'] or ''} Update: {note}.".strip()
        save(conn, "units", payload, current["id"], current["revision"])
    return {
        "buildings": len(plan.buildings),
        "units": len(plan.units),
        "updates": len(plan.updates),
    }


def import_folder(conn, folder: Path = DEFAULT_FOLDER, apply: bool = False) -> dict:
    plan = plan_import(conn, folder)
    names = {key: b["name"] for key, b in plan.buildings.items()}
    names.update(
        {
            key: b["name"]
            for b in rows(conn, "buildings")
            for key, i in plan.existing.items()
            if i == b["id"]
        }
    )
    result = plan.summary(names)
    if apply:
        result["applied"] = apply_import(conn, plan)
    else:
        result["applied"] = "dry run: nothing written (add --apply)"
    return result
