from friday_api.services.text_chunking import split_text_into_chunks


def test_chunking_empty_returns_empty() -> None:
    assert split_text_into_chunks("") == []
    assert split_text_into_chunks("   \t\n") == []


def test_chunking_splits_long_text() -> None:
    text = "x" * 2500
    chunks = split_text_into_chunks(text, max_chars=900, overlap=80)
    assert len(chunks) >= 3
    assert all(len(c) <= 900 for c in chunks)
