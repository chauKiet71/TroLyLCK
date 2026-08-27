from memory_bot.services.chunking import chunk_text


def test_empty_text_has_no_chunks() -> None:
    assert chunk_text(" \n ") == []


def test_short_text_is_one_chunk() -> None:
    assert chunk_text("Xin chao\n\nBao cao thang 8") == ["Xin chao\nBao cao thang 8"]


def test_long_text_is_split_with_limit() -> None:
    text = "\n".join(["A" * 90, "B" * 90, "C" * 90])
    chunks = chunk_text(text, max_chars=200, overlap_chars=10)
    assert len(chunks) == 2
    assert all(len(chunk) <= 200 for chunk in chunks)
