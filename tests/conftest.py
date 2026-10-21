import pytest

from apartment_hunter.db import database


@pytest.fixture
def conn(tmp_path):
    with database(tmp_path / "test.db") as connection:
        yield connection
