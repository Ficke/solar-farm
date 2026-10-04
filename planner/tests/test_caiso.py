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
