from pathlib import Path

from planner.caiso import COLUMNS
from solar_server.openapi import schema
from solar_server.schema import MixRow

OPENAPI = Path(__file__).parents[2] / "web" / "openapi.json"


def test_dashboard_schema_is_current():
    assert OPENAPI.read_text() == schema(), "API changed: run `just api`"


def test_mix_rows_carry_every_caiso_fuel():
    assert set(MixRow.model_fields) == {"t", *COLUMNS.values()}
