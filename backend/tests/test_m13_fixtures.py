import json
from pathlib import Path

import pytest

from schemas.tender import TenderRequirements
from utils.file_parser import extract_text


FIXTURES = Path(__file__).parent / "fixtures"
TENDERS = FIXTURES / "tenders"
EXPECTED = FIXTURES / "expected"


def test_m13_has_two_real_tender_files() -> None:
    tender_files = sorted(
        path
        for path in TENDERS.iterdir()
        if path.suffix.lower() in {".pdf", ".docx"} and path.is_file()
    )

    assert len(tender_files) >= 2


@pytest.mark.parametrize(
    "tender_file",
    sorted(
        path
        for path in TENDERS.iterdir()
        if path.suffix.lower() in {".pdf", ".docx"} and path.is_file()
    ),
)
def test_m13_real_tender_text_can_be_extracted(tender_file: Path) -> None:
    text = extract_text(tender_file)

    assert len(text) > 1000
    assert "招标" in text


def test_m13_expected_labels_validate_when_filled() -> None:
    expected_files = sorted(EXPECTED.glob("*_expected.json"))

    assert len(expected_files) >= 2
    empty_files = [
        path.name
        for path in expected_files
        if not path.read_text(encoding="utf-8").strip()
    ]
    if empty_files:
        pytest.skip(
            f"Expected label files are not filled yet: {', '.join(empty_files)}"
        )

    for expected_file in expected_files:
        data = json.loads(expected_file.read_text(encoding="utf-8"))
        parsed = TenderRequirements.model_validate(data)
        assert parsed.project_name
        assert (
            parsed.qualification_list
            or parsed.technical_score_items
            or parsed.invalid_bid_items
        )
