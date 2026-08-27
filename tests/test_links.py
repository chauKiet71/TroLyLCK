import pytest

from memory_bot.services.links import extract_urls, validate_public_url


def test_extract_urls_removes_trailing_punctuation() -> None:
    text = "Xem https://example.com/report.pdf, va https://example.com/report.pdf."
    assert extract_urls(text) == ["https://example.com/report.pdf"]


@pytest.mark.asyncio
async def test_private_ip_is_rejected() -> None:
    with pytest.raises(ValueError):
        await validate_public_url("http://127.0.0.1/private")
