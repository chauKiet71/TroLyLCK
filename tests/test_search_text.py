from memory_bot.services.search_text import meaningful_search_terms


def test_question_words_are_removed() -> None:
    assert meaningful_search_terms("Điện thoại iphone x mua lúc nào") == [
        "điện",
        "thoại",
        "iphone",
        "x",
        "mua",
    ]


def test_duplicate_terms_are_removed() -> None:
    assert meaningful_search_terms("báo cáo báo cáo tháng 8 ở đâu") == [
        "báo",
        "cáo",
        "tháng",
        "8",
    ]


def test_bank_alias_is_normalized_and_chat_filler_is_removed() -> None:
    assert meaningful_search_terms("có mã qr vtb ko") == ["mã", "qr", "vietinbank"]


def test_job_requirements_query_keeps_only_searchable_terms() -> None:
    assert meaningful_search_terms("Vị trí Digital ads cần có skill gì ko") == [
        "digital",
        "ads",
        "qualification",
    ]
