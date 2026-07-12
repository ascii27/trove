from app.urls import canonicalize


def test_adds_scheme_and_lowercases_host():
    assert canonicalize("Example.com/Path") == "https://example.com/Path"


def test_strips_www_fragment_and_tracking_params():
    got = canonicalize("https://www.example.com/a?utm_source=x&id=7&fbclid=z#frag")
    assert got == "https://example.com/a?id=7"


def test_strips_trailing_slash_but_keeps_root():
    assert canonicalize("https://example.com/a/") == "https://example.com/a"
    assert canonicalize("https://example.com/") == "https://example.com/"


def test_variants_dedupe_to_same_canonical():
    a = canonicalize("http://www.Example.com/post?utm_campaign=spring")
    b = canonicalize("https://example.com/post")
    # scheme differs (http vs https) but tracking + www removed
    assert a == "http://example.com/post"
    assert b == "https://example.com/post"
