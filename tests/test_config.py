from memory_bot.config import Settings


def make_settings(user_ids: str) -> Settings:
    return Settings(
        telegram_bot_token="123:test",
        database_url="postgresql://user:password@localhost/database",
        allowed_telegram_user_ids=user_ids,
    )


def test_empty_allowed_user_ids() -> None:
    assert make_settings("").allowed_telegram_user_ids == frozenset()


def test_comma_separated_allowed_user_ids() -> None:
    assert make_settings("123, 456").allowed_telegram_user_ids == frozenset({123, 456})
