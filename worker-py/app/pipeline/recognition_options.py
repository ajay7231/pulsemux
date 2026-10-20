"""Shared recognition policy: preserve spoken entities; use explicit vocabulary only.

Smart formatting rewrites spoken dates into locale-ambiguous numeric dates.
Punctuation is independent and still supplies the semantic turn detector's cues.
Vocabulary is agent configuration, never inferred from an expected transcript.
"""


def validate_keyterms(terms):
    if not isinstance(terms, list) or len(terms) > 25:
        raise ValueError("Use at most 25 recognition terms")
    result, seen = [], set()
    for term in terms:
        if not isinstance(term, str):
            raise ValueError("Recognition terms must be text")
        term = " ".join(term.split())
        if not term or len(term) > 80 or len(term.split()) > 5 or ":" in term:
            raise ValueError("Use plain recognition terms of 1–80 characters and at most five words")
        if term.casefold() not in seen:
            seen.add(term.casefold())
            result.append(term)
    return result


def deepgram_options(keyterms=()):
    return {"model": "nova-3", "language": "en", "smart_format": "false",
            "punctuate": "true", "keyterm": validate_keyterms(list(keyterms))}
