"""URL canonicalization for dedupe (PRD §11: don't create a second copy)."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "gbraid", "wbraid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid"}


def canonicalize(url: str) -> str:
    """Normalize a URL so trivially-different forms of the same page dedupe.

    - add https:// if no scheme
    - lowercase scheme + host, drop default ports
    - strip fragments and common tracking params
    - drop a trailing slash on non-root paths
    """
    raw = url.strip()
    if "://" not in raw:
        raw = "https://" + raw
    p = urlparse(raw)

    scheme = p.scheme.lower()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    netloc = host
    if p.port and p.port not in (80, 443):
        netloc = f"{host}:{p.port}"

    query = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not (k.lower() in _TRACKING_KEYS or k.lower().startswith(_TRACKING_PREFIXES))
    ]

    path = p.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunparse((scheme, netloc, path, "", urlencode(query), ""))
