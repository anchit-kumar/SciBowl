from scibowl.ui import chunks, review_pages, review_view


def payload_with_long_mistake():
    return {
        "attempts": [
            {
                "user_id": 7,
                "verdict": "incorrect",
                "answer": "my answer",
                "explanation": "explanation",
                "question": {
                    "category": "Physics",
                    "source": "DOE",
                    "page": 3,
                    "text": "Q" * 8000,
                    "choices": {"A": "choice"},
                    "answer": "correct answer",
                },
            }
        ]
    }


async def test_long_review_is_paginated_without_text_loss():
    text = "Q" * 8000
    pages = review_pages(payload_with_long_mistake(), 7)

    assert len(pages) >= 3
    assert all(len(page.description) <= 3400 for page in pages)
    assert text in "".join(page.description for page in pages)
    assert all(page.title.startswith("Question 1 of 1") for page in pages)


async def test_review_controls_are_valid_and_owner_scoped():
    view = review_view("a" * 16, 123456789, 1, 3, "missed")
    buttons = list(view.children)

    assert len(buttons) == 7
    assert {item.label for item in buttons} == {
        "First",
        "Previous",
        "Next",
        "Last",
        "Missed",
        "Skipped",
        "Ungraded",
    }
    assert all(item.custom_id and len(item.custom_id) <= 100 for item in buttons)
    assert len({item.custom_id for item in buttons}) == len(buttons)
    assert next(item for item in buttons if item.label == "Previous").disabled is False
    assert next(item for item in buttons if item.label == "Next").disabled is False
    assert next(item for item in buttons if item.label == "Missed").disabled is True


def test_chunks_preserve_plain_long_content():
    text = "abc" * 2500
    pieces = chunks(text)

    assert "".join(pieces) == text
    assert all(len(piece) <= 3400 for piece in pieces)
