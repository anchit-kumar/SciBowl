from pathlib import Path
from unittest.mock import patch

from scibowl.bank import parse_pdfs, validate_staging


class _Page:
    def __init__(self, text: str):
        self.text = text

    def extract_text(self):
        return self.text


class _Pdf:
    def __init__(self, pages):
        self.pages = [_Page(page) for page in pages]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_validate_staging_reports_malformed_json_fields_without_raising(tmp_path: Path):
    packet = tmp_path / "malformed-fields.pdf"
    packet.write_bytes(b"malformed fields")
    text = """TOSS-UP
BIOLOGY
Short Answer
What molecule carries hereditary information?
ANSWER: DNA
"""
    with patch("scibowl.bank.pdfplumber.open", return_value=_Pdf([text])):
        payload = parse_pdfs(packet, "DOE", "regional")

    record = payload["questions"][0]
    record["reviewed"] = True
    payload["metadata"]["pool"] = ["regional"]
    record["format"] = {"short_answer"}
    record["pool"] = ["regional"]
    record["role"] = {"tossup"}
    record["source"] = ["DOE"]
    record["document_checksum"] = {"not": "a checksum"}
    record["aliases"] = "DNA"

    errors = validate_staging(payload)
    assert "staging metadata has an invalid pool" in errors
    assert "question 1 has an invalid format" in errors
    assert "question 1 has an invalid pool" in errors
    assert "question 1 has an invalid role" in errors
    assert "question 1 has an invalid source" in errors
    assert "question 1 has an invalid document checksum" in errors
    assert "question 1 has invalid aliases" in errors
