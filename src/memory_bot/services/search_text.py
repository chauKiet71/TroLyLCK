from __future__ import annotations

import re

VIETNAMESE_QUERY_STOP_WORDS = {
    "ai",
    "bao",
    "bạn",
    "có",
    "cho",
    "chưa",
    "cái",
    "của",
    "do",
    "giúp",
    "gửi",
    "hình",
    "k",
    "khi",
    "không",
    "ko",
    "là",
    "lại",
    "lúc",
    "mấy",
    "mình",
    "nào",
    "như",
    "nhớ",
    "nhiêu",
    "ở",
    "rồi",
    "thấy",
    "thế",
    "tìm",
    "tôi",
    "vậy",
    "với",
    "đã",
    "đâu",
    "đúng",
    "được",
}

SEARCH_TERM_ALIASES = {
    "vtb": "vietinbank",
}


def meaningful_search_terms(text: str, max_terms: int = 12) -> list[str]:
    """Keep content words and remove conversational/question filler."""
    tokens = re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
    terms: list[str] = []
    for token in tokens:
        token = SEARCH_TERM_ALIASES.get(token, token)
        if token in VIETNAMESE_QUERY_STOP_WORDS or token in terms:
            continue
        terms.append(token)
        if len(terms) == max_terms:
            break
    return terms or tokens[:max_terms]
