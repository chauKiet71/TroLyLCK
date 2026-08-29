from memory_bot.services.message_routing import explicit_save_content


def test_explicit_save_strips_prefix_and_whitespace() -> None:
    assert (
        explicit_save_content("  ĐÂY   LÀ   Kho prompt GPT-Image-2  ")
        == "Kho prompt GPT-Image-2"
    )


def test_day_la_inside_chat_is_not_a_save() -> None:
    assert explicit_save_content("Tôi nghĩ đây là câu trả lời đúng") is None


def test_empty_explicit_save_returns_empty_content() -> None:
    assert explicit_save_content("đây là   ") == ""
