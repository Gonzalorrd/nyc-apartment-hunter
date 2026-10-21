"""Adapters never imply a live scrape occurred."""

from dataclasses import dataclass
from typing import Protocol

from apartment_hunter.services import import_csv


@dataclass
class RefreshResult:
    provider: str
    status: str
    message: str
    changed: int = 0


class Provider(Protocol):
    name: str

    def refresh(self, conn) -> RefreshResult: ...


class ManualCSVProvider:
    name = "manual_csv"

    def __init__(self, entity: str, content: str):
        self.entity, self.content = entity, content

    def refresh(self, conn) -> RefreshResult:
        changed = import_csv(conn, self.entity, self.content)
        return RefreshResult(self.name, "imported", "User-provided CSV validated", changed)


class ManualWebsiteProvider:
    def __init__(self, name: str):
        self.name = name

    def refresh(self, conn) -> RefreshResult:
        return RefreshResult(
            self.name,
            "manual_required",
            "Open the source in your browser; enter evidence or import CSV. "
            "No network request made.",
        )


def refresh_sources(conn) -> list[RefreshResult]:
    return [
        ManualWebsiteProvider(name).refresh(conn)
        for name in (
            "StreetEasy",
            "Zillow",
            "Apartments.com",
            "RentHop",
            "Realtor.com",
            "Official leasing sites",
        )
    ]
