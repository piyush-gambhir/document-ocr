"""Synthetic document data for new-profile parser and real barcode tests."""

from core.mrz_parser import icao_check_digit
from core.ocr_engine import TextRegion


def regions(*lines: str) -> list[TextRegion]:
    return [TextRegion(text, [[10, 40 * i], [500, 40 * i], [500, 40 * i + 25], [10, 40 * i + 25]], 0.97) for i, text in enumerate(lines)]


def aamva_payload(kind="DL", version=11, overrides=None, extra_subfile=True):
    elements = {
        "DAQ": "T64235789", "DCS": "SAMPLE", "DAC": "MICHAEL", "DAD": "JOHN",
        "DBB": "06062006", "DBA": "06062032", "DBD": "06062022", "DBC": "1",
        "DAG": "2300 WEST BROAD STREET", "DAI": "RICHMOND", "DAJ": "VA", "DAK": "023269000",
        "DCG": "USA", "DCA": "D", "DDE": "N", "DDF": "N", "DDG": "N",
    }
    elements.update(overrides or {})
    body = kind + "\n".join(key + value for key, value in elements.items() if value is not None) + "\r"
    extra = "ZVZVA01\r" if extra_subfile else ""
    count = 2 if extra else 1
    offset = 21 + 10 * count
    header = f"@\n\x1e\rANSI 636000{version:02d}00{count:02d}"
    directory = f"{kind}{offset:04d}{len(body):04d}"
    if extra:
        directory += f"ZV{offset + len(body):04d}{len(extra):04d}"
    return header + directory + body + extra


def td1_lines(kind="IP", issuer="USA", number="C12345678", optional="", birth="900315", expiry="300601", birth_country="USA"):
    first = kind + issuer + number.ljust(9, "<") + str(icao_check_digit(number.ljust(9, "<"))) + optional.ljust(15, "<")
    second = birth + str(icao_check_digit(birth)) + "F" + expiry + str(icao_check_digit(expiry)) + birth_country + "<" * 11
    second += str(icao_check_digit(first[5:30] + second[:7] + second[8:15] + second[18:29]))
    return [first, second, "SAMPLE<<ANNA<MARIA".ljust(30, "<")]


def visa_lines(width=44):
    # The number/DOB/expiry check digits are the independent ICAO specimen
    # values 6, 2 and 9. Visas have no composite check digit.
    return ["V<USASAMPLE<<ANNA<MARIA".ljust(width, "<"), "L898902C36USA7408122F1204159".ljust(width, "<")]
