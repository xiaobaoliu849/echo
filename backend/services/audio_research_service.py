from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import re
import socket
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx


USER_AGENT = (
    "VoiceSpiritResearchAgent/1.0 "
    "(local podcast research; contact: voicespirit.local)"
)
# DuckDuckGo HTML endpoints, tried in order. The canonical ``html.duckduckgo.com``
# host is the most reliable: the bare ``duckduckgo.com/html/`` URL is a 302 redirect
# that frequently resolves to a Teredo/IPv6 address (e.g. 2001::/32) which our
# public-address guard rejects, silently yielding zero results. Trying the canonical
# host first avoids that failure mode.
DUCKDUCKGO_HTML_ENDPOINTS = (
    "https://html.duckduckgo.com/html/?q={query}",
    "https://duckduckgo.com/html/?q={query}",
)
MAX_SOURCE_CONTENT_CHARS = 5000
MAX_SEARCH_RESULTS = 5
REQUEST_TIMEOUT_SECONDS = 10.0
# Per-endpoint budget for DuckDuckGo attempts inside search(). DDG is unreachable
# from mainland China without a proxy, where a connection attempt hangs until the
# full REQUEST_TIMEOUT_SECONDS. Two endpoints at 10s each (20s) exceed the 15s
# total budget that VoiceAgentToolService.run_search enforces, so the cn.bing.com
# fallback (China-accessible) never got a chance to run. Capping each DDG attempt
# at 4s guarantees Bing always gets the remaining budget.
DDG_PER_ENDPOINT_TIMEOUT_SECONDS = 4.0
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 600_000
_IPV4_NUMBER_LABEL_PATTERN = re.compile(r"^(?:0x[0-9a-f]+|\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class ResearchDocument:
    title: str
    url: str
    snippet: str
    content: str
    score: float
    source_type: str
    meta: dict[str, Any]

    def to_source(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "title": self.title,
            "uri": self.url,
            "snippet": self.snippet,
            "content": self.content,
            "score": self.score,
            "meta": self.meta,
        }


class HtmlContentExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name == "title":
            self._in_title = True
            return
        if tag_name in {"script", "style", "noscript", "svg", "canvas", "form", "nav", "footer", "header"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "title":
            self._in_title = False
            return
        if tag_name in {"script", "style", "noscript", "svg", "canvas", "form", "nav", "footer", "header"}:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        text = _normalize_whitespace(data)
        if not text:
            return
        if self._in_title:
            self.title = _normalize_whitespace(f"{self.title} {text}")[:240]
            return
        if self._skip_depth:
            return
        if len(text) >= 24:
            self._chunks.append(text)

    @property
    def text(self) -> str:
        return _normalize_whitespace("\n".join(self._chunks))


class DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._capture_link = False
        self._capture_snippet = False
        self._current_href = ""
        self._current_title_parts: list[str] = []
        self._current_snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value or "" for name, value in attrs}
        class_name = attrs_dict.get("class", "")
        if tag.lower() == "a" and "result__a" in class_name:
            self._capture_link = True
            self._current_href = attrs_dict.get("href", "")
            self._current_title_parts = []
            return
        if "result__snippet" in class_name:
            self._capture_snippet = True
            self._current_snippet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._capture_link:
            title = _normalize_whitespace(" ".join(self._current_title_parts))
            resolved_url = _normalize_duckduckgo_url(self._current_href)
            if title and resolved_url:
                self.results.append({"title": title[:240], "url": resolved_url, "snippet": ""})
            self._capture_link = False
            self._current_href = ""
            self._current_title_parts = []
            return
        if self._capture_snippet and tag.lower() in {"a", "div"}:
            snippet = _normalize_whitespace(" ".join(self._current_snippet_parts))[:500]
            if snippet and self.results:
                self.results[-1]["snippet"] = snippet
            self._capture_snippet = False
            self._current_snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_link:
            self._current_title_parts.append(data)
        elif self._capture_snippet:
            self._current_snippet_parts.append(data)


class BingResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._in_b_algo = False
        self._in_h2 = False
        self._capture_title = False
        self._capture_snippet = False
        self._current_href = ""
        self._current_title_parts: list[str] = []
        self._current_snippet_parts: list[str] = []
        self._snippet_tag_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value or "" for name, value in attrs}
        class_name = attrs_dict.get("class", "")
        tag_name = tag.lower()

        if tag_name == "li" and "b_algo" in class_name:
            self._in_b_algo = True
            self._current_href = ""
            self._current_title_parts = []
            self._current_snippet_parts = []
            self._capture_title = False
            self._capture_snippet = False
            return

        if self._in_b_algo:
            if tag_name == "h2":
                self._in_h2 = True
                return
            if self._in_h2 and tag_name == "a":
                self._capture_title = True
                self._current_href = attrs_dict.get("href", "")
                return
            
            if ("b_caption" in class_name or "b_snippet" in class_name or tag_name == "p") and not self._capture_snippet:
                if self._current_href and self._current_title_parts:
                    self._capture_snippet = True
                    self._snippet_tag_depth = 1
                    return

            if self._capture_snippet:
                self._snippet_tag_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "li" and self._in_b_algo:
            self._in_b_algo = False
            title = _normalize_whitespace(" ".join(self._current_title_parts))
            url = self._current_href.strip()
            snippet = _normalize_whitespace(" ".join(self._current_snippet_parts))[:500]
            if title and url and url.startswith(("http://", "https://")):
                self.results.append({"title": title[:240], "url": url, "snippet": snippet})
            return

        if self._in_b_algo:
            if tag_name == "h2":
                self._in_h2 = False
                return
            if tag_name == "a" and self._capture_title:
                self._capture_title = False
                return
            
            if self._capture_snippet:
                self._snippet_tag_depth -= 1
                if self._snippet_tag_depth <= 0:
                    self._capture_snippet = False

    def handle_data(self, data: str) -> None:
        if self._in_b_algo:
            if self._capture_title:
                self._current_title_parts.append(data)
            elif self._capture_snippet:
                self._current_snippet_parts.append(data)


_CONVERSATIONAL_PREFIXES = re.compile(
    r"^(?:hey\s*,?\s*|hello\s*,?\s*|please\s*|can you search about the\s*|can you search for\s*|can you search\s*|search about the\s*|search for the\s*|search about\s*|search for\s*|请问|请|帮我|帮我查一下|帮我搜索|我想知道|我想了解|搜索一下|查一下|查找|查找关于|检索|search for|please search|please query|tell me about|can you search|can you find)\s*",
    re.IGNORECASE,
)

_CONVERSATIONAL_SUFFIXES = re.compile(
    r"\s*(?:for me\s*\.?|thank you\s*\.?|thanks\s*\.?|please\s*\.?|谢谢\s*\.?|非常感谢\s*\.?)$",
    re.IGNORECASE,
)


def refine_search_query(query: str) -> str:
    cleaned = _normalize_whitespace(query)
    if not cleaned:
        return ""
    refined = _CONVERSATIONAL_PREFIXES.sub("", cleaned).strip()
    refined = _CONVERSATIONAL_SUFFIXES.sub("", refined).strip()
    return refined or cleaned


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _normalize_duckduckgo_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.path.startswith("/l/"):
        params = parse_qs(parsed.query)
        uddg = params.get("uddg", [""])[0]
        return unquote(uddg)
    if parsed.scheme in {"http", "https"}:
        return raw
    return urljoin("https://duckduckgo.com", raw)


def _is_duckduckgo_ad_url(value: str) -> bool:
    """Detect DuckDuckGo sponsored/tracking links.

    Organic DDG results always point to an external domain. Anything that still
    resolves to a duckduckgo.com host after normalization (e.g. the ``y.js``
    ad-redirect used for sponsored placements) is an ad or tracking link and
    would only pollute the grounding context, so it is filtered out.
    """
    try:
        hostname = (urlparse(str(value or "")).hostname or "").strip().lower()
    except Exception:
        return True
    if not hostname:
        return True
    return hostname == "duckduckgo.com" or hostname.endswith(".duckduckgo.com")


def _looks_like_nonstandard_ipv4(hostname: str) -> bool:
    labels = hostname.split(".")
    return 1 <= len(labels) <= 4 and all(
        bool(_IPV4_NUMBER_LABEL_PATTERN.fullmatch(label)) for label in labels
    )


def _is_safe_public_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname or hostname in {"localhost", "127.0.0.1", "::1"}:
        return False
    if hostname.endswith(".local") or hostname.endswith(".localhost"):
        return False
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return not _looks_like_nonstandard_ipv4(hostname)
    if str(ip) != hostname.strip("[]"):
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _resolve_public_host(hostname: str, port: int | None) -> list[str]:
    normalized = hostname.strip().lower().rstrip(".")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            normalized,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host: {normalized}") from exc

    resolved: list[tuple[int, str]] = []
    for family, _socktype, _proto, _canonname, sockaddr in addresses:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        ip_text = str(sockaddr[0])
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            # Unparseable answer — skip it rather than aborting the whole lookup.
            continue
        is_clash_fake_ip = False
        try:
            is_clash_fake_ip = ip in ipaddress.ip_network("198.18.0.0/15")
        except Exception:
            pass
        # 6to4 (2002::/16) can embed an arbitrary IPv4 (including a private one such as
        # 2002:7f00:1::1 -> 127.0.0.1) and Python's ipaddress does NOT flag it as private,
        # so reject it explicitly. 6to4 is deprecated (RFC 7526) and never needed to fetch
        # public search results, so skipping it only tightens the SSRF guard.
        is_6to4 = False
        try:
            is_6to4 = ip in ipaddress.ip_network("2002::/16")
        except Exception:
            pass

        if is_6to4 or (
            not is_clash_fake_ip and (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            )
        ):
            # Skip non-public answers (e.g. Teredo 2001::/32, ULA, loopback) instead
            # of aborting: DNS frequently returns a transitional IPv6 address alongside
            # a usable IPv4 address, and a single non-public answer must not discard the
            # valid public ones. Non-public addresses are never used to connect, so the
            # SSRF guarantee is preserved — a host that resolves ONLY to non-public
            # addresses still fails below.
            continue
        # Sort key 0 = IPv4, 1 = IPv6: prefer IPv4 to avoid Teredo/IPv6-transition
        # flakiness while keeping every usable public address as a fallback.
        resolved.append((0 if family == socket.AF_INET else 1, ip_text))
    if not resolved:
        raise ValueError(f"Host did not resolve to a public address: {normalized}")
    resolved.sort(key=lambda item: item[0])
    return [ip_text for _, ip_text in resolved]


class AudioResearchService:
    _logger = logging.getLogger(__name__)

    async def _validate_public_target(self, url: str) -> list[str]:
        if not _is_safe_public_url(url):
            raise ValueError("URL is not a public HTTP(S) source")
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").strip()
        if not hostname:
            raise ValueError("URL host is empty")
        return await _resolve_public_host(hostname, parsed.port)

    @staticmethod
    def _request_public_url_once(url: str, ip_address: str) -> httpx.Response:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        with httpx.Client(follow_redirects=False, timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.get(url, headers=headers)
            response.request = httpx.Request("GET", url)
            return response

    async def _get_public_response(self, url: str) -> httpx.Response:
        current_url = url
        response: httpx.Response | None = None
        for _ in range(MAX_REDIRECTS + 1):
            resolved_addresses = await self._validate_public_target(current_url)
            try:
                response = await asyncio.to_thread(
                    self._request_public_url_once,
                    current_url,
                    resolved_addresses[0],
                )
            except (OSError, TimeoutError, ssl.SSLError) as exc:
                raise httpx.TransportError(
                    f"Network error while fetching source: {exc}",
                    request=httpx.Request("GET", current_url),
                ) from exc
            if not response.is_redirect:
                response.raise_for_status()
                return response
            location = response.headers.get("location", "")
            if not location:
                response.raise_for_status()
            current_url = urljoin(str(response.url), location)
        request = response.request if response is not None else httpx.Request("GET", url)
        raise httpx.TooManyRedirects(
            f"Exceeded {MAX_REDIRECTS} redirects while fetching source",
            request=request,
        )

    async def search(self, query: str, *, limit: int = MAX_SEARCH_RESULTS) -> list[dict[str, str]]:
        cleaned = refine_search_query(query)
        if not cleaned:
            self._logger.info("voice_search_skipped reason=empty_query")
            return []

        # 1. Attempt DuckDuckGo search first, trying each HTML endpoint in order.
        #    The canonical html.duckduckgo.com host is tried before the redirecting
        #    duckduckgo.com/html/ URL (see DUCKDUCKGO_HTML_ENDPOINTS).
        encoded_query = quote_plus(cleaned)
        target_limit = max(1, min(limit, MAX_SEARCH_RESULTS))
        for endpoint in DUCKDUCKGO_HTML_ENDPOINTS:
            ddg_url = endpoint.format(query=encoded_query)
            try:
                response = await asyncio.wait_for(
                    self._get_public_response(ddg_url),
                    timeout=DDG_PER_ENDPOINT_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                parser = DuckDuckGoResultParser()
                parser.feed(response.text[:300_000])
                results: list[dict[str, str]] = []
                seen: set[str] = set()
                for item in parser.results:
                    url = item.get("url", "")
                    if not _is_safe_public_url(url) or _is_duckduckgo_ad_url(url) or url in seen:
                        continue
                    seen.add(url)
                    results.append(item)
                    if len(results) >= target_limit:
                        break
                self._logger.info(
                    "voice_search_result engine=duckduckgo endpoint=%s query=%r count=%s titles=%s",
                    ddg_url.split("?")[0], cleaned[:200], len(results),
                    [r.get("title", "")[:80] for r in results],
                )
                if results:
                    return results
            except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as exc:
                self._logger.warning(
                    "voice_search_duckduckgo_failed endpoint=%s query=%r error=%s",
                    ddg_url.split("?")[0], cleaned[:200], exc,
                )

        # 2. Fallback to cn.bing.com search (accessible in China)
        bing_url = f"https://cn.bing.com/search?q={quote_plus(cleaned)}"
        try:
            response = await self._get_public_response(bing_url)
            response.raise_for_status()
            parser = BingResultParser()
            parser.feed(response.text[:300_000])
            results = []
            seen = set()
            for item in parser.results:
                url = item.get("url", "")
                if not _is_safe_public_url(url) or url in seen:
                    continue
                seen.add(url)
                results.append(item)
                if len(results) >= max(1, min(limit, MAX_SEARCH_RESULTS)):
                    break
            self._logger.info(
                "voice_search_result engine=bing query=%r count=%s titles=%s",
                cleaned[:200], len(results),
                [r.get("title", "")[:80] for r in results],
            )
            return results
        except (httpx.HTTPError, ValueError) as exc:
            self._logger.warning("voice_search_bing_failed query=%r error=%s", cleaned[:200], exc)
            return []

    async def fetch_document(
        self,
        url: str,
        *,
        title_hint: str = "",
        snippet_hint: str = "",
        source_type: str = "web_page",
        score: float = 0.7,
    ) -> ResearchDocument:
        clean_url = str(url or "").strip()
        title = _normalize_whitespace(title_hint) or clean_url[:160]
        snippet = _normalize_whitespace(snippet_hint)
        if not _is_safe_public_url(clean_url):
            return ResearchDocument(
                title=title,
                url=clean_url[:1000],
                snippet=snippet or "URL was skipped because it is not a public HTTP(S) source.",
                content="",
                score=0.0,
                source_type=source_type,
                meta={"fetch_status": "skipped", "reason": "unsafe_or_unsupported_url"},
            )

        try:
            response = await self._get_public_response(clean_url)
        except (httpx.HTTPError, ValueError) as exc:
            return ResearchDocument(
                title=title,
                url=clean_url[:1000],
                snippet=snippet or f"Failed to fetch source: {exc}",
                content="",
                score=max(0.1, score - 0.4),
                source_type=source_type,
                meta={"fetch_status": "failed", "error": str(exc)[:300]},
            )

        content_type = response.headers.get("content-type", "")
        text = response.text[:500_000]
        extractor = HtmlContentExtractor()
        if "html" in content_type.lower() or "<html" in text[:1000].lower():
            extractor.feed(text)
            extracted = extractor.text[:MAX_SOURCE_CONTENT_CHARS]
            title = extractor.title or title
        else:
            extracted = _normalize_whitespace(text)[:MAX_SOURCE_CONTENT_CHARS]

        if not snippet:
            snippet = extracted[:500]
        return ResearchDocument(
            title=title,
            url=str(response.url)[:1000],
            snippet=snippet[:500],
            content=extracted,
            score=score if extracted else max(0.1, score - 0.3),
            source_type=source_type,
            meta={
                "fetch_status": "ok" if extracted else "empty",
                "content_type": content_type[:120],
                "content_length": len(extracted),
            },
        )
