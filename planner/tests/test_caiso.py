from datetime import date

from planner import caiso

HEADER = (
    "Time,Solar,Wind,Geothermal,Biomass,Biogas,Small hydro,Coal,Nuclear,"
    "Natural Gas,Large Hydro,Batteries,Imports,Other"
)
ROWS = """
00:00,-48,936,780,190,152,227,3,2228,14705,2616,1729,5705,0
12:05,15000,500,780,190,152,227,3,2228,3000,2616,-4000,2000,
"""


def test_parse_reads_megawatts_by_fuel_on_pacific_time():
    rows = caiso.parse("\N{ZERO WIDTH NO-BREAK SPACE}" + HEADER + ROWS, date(2026, 10, 4))
    assert [r["t"] for r in rows] == [1791097200, 1791097200 + 12 * 3600 + 300]
    assert rows[0]["gas"] == 14705 and rows[0]["large_hydro"] == 2616
    assert rows[1]["batteries"] == -4000 and rows[1]["other"] is None


# The columns parse_prices reads, out of OASIS's 16.
PRICE_CSV = """INTERVALSTARTTIME_GMT,NODE,LMP_TYPE,MW
2026-10-04T15:45:00-00:00,TH_NP15_GEN-APND,LMP,29.94071
2026-10-04T15:45:00-00:00,TH_NP15_GEN-APND,MCC,5.1
2026-10-04T15:45:00-00:00,TH_SP15_GEN-APND,LMP,22.09236
2026-10-04T15:40:00-00:00,TH_SP15_GEN-APND,LMP,-3.5
2026-10-04T15:40:00-00:00,TH_ZP26_GEN-APND,LMP,20
"""


def test_parse_prices_keeps_lmp_by_hub_and_interval_start():
    rows = caiso.parse_prices(PRICE_CSV)
    assert rows == [
        {"t": 1791128400, "np15": None, "sp15": -3.5},
        {"t": 1791128700, "np15": 29.94, "sp15": 22.09},
    ]
