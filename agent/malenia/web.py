"""Explicit public search snippets. Never fetch result URLs or private context."""
from __future__ import annotations
import ipaddress
import re
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

class WebError(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WebError("web_redirect_rejected")

def public_link(value):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 33 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").rstrip(".")
        if (parsed.scheme not in ("http", "https") or parsed.username or parsed.password
                or parsed.port not in (None, 80, 443) or "\\" in value or "%" in host
                or "." not in host or host.endswith((".local", ".localhost", ".internal", ".test", ".invalid"))):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return bool(re.fullmatch(r"[a-zA-Z0-9.-]+", host)) and not host.replace(".", "").isdigit()
    except ValueError:
        return False

def clean(value, limit):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", value or ""))).strip()[:limit]

class PublicSearch:
    def __init__(self):
        self._opener = build_opener(ProxyHandler({}), NoRedirect())

    def search(self, query):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
            raise WebError("invalid_web_query")
        # Fixed endpoint: links in results are displayed, never followed here.
        request = Request("https://www.bing.com/search?" + urlencode({"format": "rss", "q": query}),
                          headers={"User-Agent": "Malenia/0.6 public-search", "Accept": "application/rss+xml"})
        try:
            with self._opener.open(request, timeout=15) as response:
                raw = response.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise WebError("web_invalid_response")
            xml = raw.decode("utf-8-sig")
            if "\x00" in xml:
                raise WebError("web_invalid_response")
            root = ET.fromstring(xml)
            if root.tag != "rss":
                raise WebError("web_invalid_response")
            sources, seen = [], set()
            for item in root.findall("./channel/item")[:20]:
                link = (item.findtext("link") or "").strip()
                title, excerpt = clean(item.findtext("title"), 160), clean(item.findtext("description"), 600)
                if not public_link(link) or not title or not excerpt or link in seen:
                    continue
                seen.add(link)
                sources.append({"id": "web-" + str(len(sources) + 1), "title": title,
                                "source": link, "url": link, "kind": "web", "excerpt": excerpt})
                if len(sources) == 4:
                    break
            return sources
        except WebError:
            raise
        except Exception:
            raise WebError("web_search_unavailable") from None
