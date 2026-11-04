"""Contract test for LiveLeieAdapter against the real LEIE CSV's
column shape (SPEC.md section 7.6) - verified 2026-11-04 by
downloading the real file directly (see live_leie.py's module
docstring for the exact header and why that mattered: a web search
summary of the columns didn't exactly match the real file). The rows
below are entirely synthetic - never a real excluded person's name
(CLAUDE.md invariant 4) - but use the real header so this test proves
the parser against the actual column layout, not a hypothetical one.

No real download happens here: the adapter's `_ensure_downloaded` is
monkeypatched to return a small synthetic CSV string directly. A real
~10MB download was done once manually during development to verify
the column header (recorded in live_leie.py's docstring); it is not
repeated by any automated test to avoid hammering the real endpoint.
"""

from __future__ import annotations

from pathlib import Path

from app.tools_mcp.live_leie import LiveLeieAdapter

_REAL_HEADER = (
    "LASTNAME,FIRSTNAME,MIDNAME,BUSNAME,GENERAL,SPECIALTY,UPIN,NPI,DOB,"
    "ADDRESS,CITY,STATE,ZIP,EXCLTYPE,EXCLDATE,REINDATE,WAIVERDATE,WVRSTATE"
)
_SYNTHETIC_CSV = "\n".join(
    [
        _REAL_HEADER,
        'DOE,JANE,,,INDIVIDUAL,COUNSELOR,,1999999999,,123 FAKE ST,AUSTIN,TX,78701,'
        "1128a1,20200101,0,0,",
        'SMITH,PAT,,,INDIVIDUAL,,,,,456 FAKE AVE,DALLAS,TX,75201,1128b4,20190601,0,0,',
    ]
)


def _adapter(tmp_path: Path) -> LiveLeieAdapter:
    adapter = LiveLeieAdapter(cache_path=tmp_path / "leie.csv")
    adapter._ensure_downloaded = lambda: _SYNTHETIC_CSV  # type: ignore[method-assign]
    return adapter


def test_exact_name_match_reports_possible_match(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    result = adapter.check("Jane Doe")
    assert result == {"possible_match": True, "npi": "1999999999"}


def test_no_match_reports_possible_match_false(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    result = adapter.check("Someone Else")
    assert result == {"possible_match": False, "npi": None}


def test_a_row_with_no_npi_reports_npi_none(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    result = adapter.check("Pat Smith")
    assert result == {"possible_match": True, "npi": None}


def test_npi_disambiguates_among_same_name_matches(tmp_path: Path) -> None:
    csv_text = "\n".join(
        [
            _REAL_HEADER,
            'DOE,JANE,,,INDIVIDUAL,,,1111111111,,,,,,1128a1,20200101,0,0,',
            'DOE,JANE,,,INDIVIDUAL,,,2222222222,,,,,,1128a1,20210101,0,0,',
        ]
    )
    adapter = LiveLeieAdapter(cache_path=tmp_path / "leie.csv")
    adapter._ensure_downloaded = lambda: csv_text  # type: ignore[method-assign]
    result = adapter.check("Jane Doe", npi="2222222222")
    assert result == {"possible_match": True, "npi": "2222222222"}


def test_index_is_only_built_once_per_adapter_instance(tmp_path: Path) -> None:
    calls = {"count": 0}
    adapter = LiveLeieAdapter(cache_path=tmp_path / "leie.csv")

    def fake_download() -> str:
        calls["count"] += 1
        return _SYNTHETIC_CSV

    adapter._ensure_downloaded = fake_download  # type: ignore[method-assign]
    adapter.check("Jane Doe")
    adapter.check("Someone Else")
    assert calls["count"] == 1
