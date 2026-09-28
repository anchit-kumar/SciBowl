from pathlib import Path
from unittest.mock import patch

import pytest

from scibowl.bank import load_approved, parse_pdfs, validate_staging


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


def test_parse_doe_style_pdf_creates_unreviewed_staging(tmp_path: Path):
    packet = tmp_path / "packet.pdf"
    packet.write_bytes(b"synthetic pdf")
    text = """TOSS-UP
BIOLOGY
Short Answer
What molecule carries hereditary information?
ANSWER: DNA
BONUS
CHEMISTRY
Multiple Choice
Which element has atomic number 1?
(W) Helium
(X) Hydrogen
(Y) Oxygen
ANSWER: X
"""
    with patch("scibowl.bank.pdfplumber.open", return_value=_Pdf([text])):
        payload = parse_pdfs(packet, "DOE High School", "regional", "https://example.test/packet")

    assert payload["metadata"]["source_kind"] == "doe"
    assert len(payload["questions"]) == 2
    tossup, bonus = payload["questions"]
    assert tossup["role"] == "tossup"
    assert tossup["category"] == "Biology"
    assert tossup["reviewed"] is False
    assert bonus["format"] == "multiple_choice"
    assert bonus["choices"]["X"] == "Hydrogen"
    assert bonus["source_url"] == "https://example.test/packet"
    assert validate_staging(payload) == [
        "question 1 has not been reviewed",
        "question 2 has not been reviewed",
    ]


def test_review_gate_and_dedup_stable_id(tmp_path: Path):
    packet = tmp_path / "mit.pdf"
    packet.write_bytes(b"same content")
    text = """TOSS-UP
PHYSICS
Short Answer
What is the SI unit of force?
ANSWER: newton
"""
    with patch("scibowl.bank.pdfplumber.open", return_value=_Pdf([text])):
        first = parse_pdfs(packet, "MIT Science Bowl", "invitational")
        second = parse_pdfs(packet, "MIT Science Bowl", "invitational")
    assert first["questions"][0]["id"] == second["questions"][0]["id"]
    with pytest.raises(ValueError, match="has not been reviewed"):
        load_approved(first)
    first["questions"][0]["reviewed"] = True
    questions = load_approved(first)
    assert questions[0].id == first["questions"][0]["id"]
    assert questions[0].source == "MIT Science Bowl"
    assert questions[0].document_checksum == first["questions"][0]["document_checksum"]


def test_inline_doe_headers_multiline_options_and_pairing(tmp_path: Path):
    packet = tmp_path / "regional.pdf"
    packet.write_bytes(b"first packet")
    text = """ROUND 1
TOSS-UP
1) Math – Short Answer
What is 2 + 2?
ANSWER: 4
TOSS-UP
2) Earth and Space Science - Multiple Choice
Which world is known as the red planet?
(W) Mercury
(X) Mars, the fourth planet
from the Sun
(Y) Venus
ANSWER: X) Mars, the fourth planet from the Sun
BONUS
2) Earth & Space – Short Answer
Name the red planet.
ANSWER: Mars
National Science Bowl
"""
    with patch("scibowl.bank.pdfplumber.open", return_value=_Pdf([text])):
        payload = parse_pdfs(packet, "DOE", "regional")

    tossup_one, tossup_two, bonus = payload["questions"]
    assert tossup_one["category"] == "Mathematics"
    assert tossup_two["category"] == "Earth and Space Science"
    assert tossup_two["choices"]["X"] == "Mars, the fourth planet from the Sun"
    assert tossup_two["pair_id"] == bonus["pair_id"]
    assert tossup_two["document_checksum"]
    assert "National Science Bowl" not in bonus["text"]


def test_id_deduplicates_identical_content_from_different_packets(tmp_path: Path):
    first_packet = tmp_path / "first.pdf"
    second_packet = tmp_path / "second.pdf"
    first_packet.write_bytes(b"first")
    second_packet.write_bytes(b"second")
    text = """TOSS-UP
1) Physics – Short Answer
What is the SI unit of force?
ANSWER: newton
"""
    with patch("scibowl.bank.pdfplumber.open", return_value=_Pdf([text])):
        first = parse_pdfs(first_packet, "DOE", "regional")
        second = parse_pdfs(second_packet, "Stanford", "invitational")
    assert first["questions"][0]["id"] == second["questions"][0]["id"]
    assert first["questions"][0]["document_checksum"] != second["questions"][0]["document_checksum"]


def test_malformed_and_scanned_pages_are_flagged(tmp_path: Path):
    packet = tmp_path / "stanford.pdf"
    packet.write_bytes(b"different content")
    malformed = """TOSS-UP
MATHEMATICS
Multiple Choice
What is two plus two?
(A) Four
"""
    with patch("scibowl.bank.pdfplumber.open", return_value=_Pdf([malformed, ""])):
        payload = parse_pdfs(packet, "Stanford Invitational", "invitational")
    assert payload["questions"] == []
    joined = " ".join(payload["issues"])
    assert "missing answer" in joined
    assert "malformed multiple-choice" in joined
    assert "no extractable text" in joined


def test_issues_require_explicit_acknowledgement_before_import(tmp_path: Path):
    packet = tmp_path / "generic.pdf"
    packet.write_bytes(b"generic")
    text = """BIOLOGY
Short Answer
What carries hereditary information?
ANSWER: DNA
"""
    with patch("scibowl.bank.pdfplumber.open", return_value=_Pdf([text])):
        payload = parse_pdfs(packet, "Generic", "regional")
    payload["questions"][0]["reviewed"] = True
    assert "staging issues have not been explicitly acknowledged" in validate_staging(payload)
    payload["issues_acknowledged"] = True
    assert validate_staging(payload) == []


def test_extraction_damage_after_answer_and_lost_superscript_are_flagged(tmp_path: Path):
    packet = tmp_path / "damage.pdf"
    packet.write_bytes(b"damage")
    text = """TOSS-UP
1) Physics - Multiple Choice Which quantity equals 10 –3 meters?
W) A millimeter
X) A kilometer
ANSWER: W)Amillimeter
2
"""
    with patch("scibowl.bank.pdfplumber.open", return_value=_Pdf([text])):
        payload = parse_pdfs(packet, "DOE", "regional")
    joined = " ".join(payload["issues"])
    assert "missing whitespace" in joined
    assert "unexpected non-footer content after ANSWER" in joined
    assert "lost superscript" in joined
