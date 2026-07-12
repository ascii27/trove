import httpx
import pytest

from app import extract

_PARA = (
    "A platform is a product whose only customers are engineers, and engineers "
    "are the most ruthless users alive: they will route around anything slower "
    "than the thing they already know how to do by hand today."
)


def _article_html(n_paragraphs: int) -> str:
    body = "".join(f"<p>{_PARA}</p>" for _ in range(n_paragraphs))
    return f"""<!doctype html><html><head>
    <title>The anatomy of an internal developer platform</title>
    <meta name="author" content="Susanne Kaiser">
    <meta property="og:site_name" content="martinfowler.com">
    </head><body><article><h1>The anatomy of an internal developer platform</h1>
    {body}</article></body></html>"""


def test_extract_success_populates_metadata_and_content():
    result = extract.extract_from_html(_article_html(8), "https://martinfowler.com/idp")
    assert result.status == "extracted"
    assert result.title == "The anatomy of an internal developer platform"
    assert result.content_text and "platform is a product" in result.content_text
    assert result.word_count > 100
    assert result.reading_minutes >= 1


def test_extract_short_capture_is_partial():
    result = extract.extract_from_html(_article_html(1), "https://example.com/stub")
    assert result.status == "partial"
    assert result.word_count < 100


def test_extract_empty_document_fails():
    result = extract.extract_from_html("", "https://example.com/x")
    assert result.status == "failed"
    assert result.error


def test_fetch_and_extract_handles_unreachable_url():
    def boom(_url):
        raise httpx.ConnectError("nope")

    result = extract.fetch_and_extract("https://nope.invalid", fetcher=boom)
    assert result.status == "failed"
    assert "reach" in result.error.lower()


def test_fetch_and_extract_handles_http_error():
    def not_found(_url):
        req = httpx.Request("GET", "https://example.com/missing")
        resp = httpx.Response(404, request=req)
        raise httpx.HTTPStatusError("404", request=req, response=resp)

    result = extract.fetch_and_extract("https://example.com/missing", fetcher=not_found)
    assert result.status == "failed"
    assert "404" in result.error
