"""Transport layer — how requests reach JobStreet when Cloudflare blocks you.

JobStreet sits behind Cloudflare's Managed Challenge. From a datacenter IP
(the usual VPS) every request gets a 403 interstitial. Two ways through:

  KeenableRelay  — GET-only third-party fetcher. No auth, no setup. Reaches
                   every public GET (REST search, SSR HTML). Cannot POST.
  DirectRelay    — plain requests. Works when you are NOT blocked (your own
                   machine, or an SSH tunnel: ssh -R 9999:id.jobstreet.com:443).
                   Required for GraphQL POST and any cookie-bearing call.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import requests

KEENABLE_ENDPOINT = "https://api.keenable.ai/v1/fetch/public"
KEENABLE_HEADERS = {"X-Keenable-Title": "hermes-agent", "User-Agent": "hermes-agent"}

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class RelayError(RuntimeError):
    """A relay could not deliver the request."""


class Relay:
    """Base transport. Subclasses implement get/post returning (status, text)."""

    def get(self, url: str, **_) -> tuple[int, str]:  # pragma: no cover
        raise NotImplementedError

    def get_full(self, url: str, **_) -> Dict[str, Any]:
        """Like get(), but keeps relay metadata (page title, final URL)."""
        status, text = self.get(url, **_)
        return {"status": status, "content": text, "title": "", "url": url}

    def post(self, url: str, body: Optional[dict] = None, **_) -> tuple[int, str]:
        raise RelayError(f"{type(self).__name__} does not support POST")

    def supports_post(self) -> bool:
        return False


class KeenableRelay(Relay):
    """GET-only public fetcher — the zero-setup path past Cloudflare.

    Free, no key, but:
      * GET only (no GraphQL POST, no cookie passthrough)
      * responses truncate around 50 KB — keep pageSize <= 25
      * long query strings occasionally 422; retry, then shorten
    """

    def __init__(self, retries: int = 3, timeout: int = 90, delay: float = 2.0):
        self.retries = retries
        self.timeout = timeout
        self.delay = delay

    def get(self, url: str, **_) -> tuple[int, str]:
        last = None
        for attempt in range(self.retries):
            try:
                r = requests.get(
                    KEENABLE_ENDPOINT,
                    params={"url": url},
                    headers=KEENABLE_HEADERS,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last = str(exc)
                time.sleep(self.delay)
                continue

            if r.status_code != 200:
                last = f"relay HTTP {r.status_code}: {r.text[:160]}"
                time.sleep(self.delay)
                continue

            content = r.json().get("content") or ""
            if not content:
                last = "relay returned empty content"
                time.sleep(self.delay)
                continue
            self._last_title = r.json().get("title") or ""
            return 200, content
        raise RelayError(f"Keenable failed after {self.retries} tries: {last}")

    def get_full(self, url: str, **_) -> Dict[str, Any]:
        status, text = self.get(url, **_)
        return {"status": status, "content": text, "title": getattr(self, "_last_title", ""), "url": url}

    def post(self, url: str, body: Optional[dict] = None, **_) -> tuple[int, str]:
        raise RelayError(
            "Keenable is GET-only. GraphQL POST needs DirectRelay — run on your own "
            "machine or through an SSH tunnel (ssh -R 9999:id.jobstreet.com:443)."
        )


class DirectRelay(Relay):
    """Plain HTTP with optional cookies — for GraphQL and authenticated calls.

    Only works from an IP Cloudflare trusts. On a blocked VPS, tunnel first:

        ssh -R 9999:id.jobstreet.com:443 user@host

    then point this relay at https://localhost:9999.
    """

    def __init__(
        self,
        cookies: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: int = 45,
        retries: int = 2,
        base_override: Optional[str] = None,
    ):
        self.cookies = cookies or {}
        self.timeout = timeout
        self.retries = retries
        self.base_override = base_override
        self.session = requests.Session()
        self.headers = {
            "User-Agent": DEFAULT_UA,
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        }
        self.headers.update(headers or {})

    @classmethod
    def from_cookie_file(cls, path: str, **kwargs) -> "DirectRelay":
        """Load a browser-exported cookie JSON (list of {name, value, ...})."""
        with open(path) as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            cookies = dict(raw)
        else:
            cookies = {c["name"]: c["value"] for c in raw if "name" in c}
        return cls(cookies=cookies, **kwargs)

    def _url(self, url: str) -> str:
        if self.base_override:
            for host in ("https://id.jobstreet.com", "https://my.jobstreet.com"):
                if url.startswith(host):
                    return self.base_override + url[len(host):]
        return url

    def _request(self, method: str, url: str, body: Optional[dict]) -> tuple[int, str]:
        last = None
        for attempt in range(self.retries):
            try:
                r = self.session.request(
                    method,
                    self._url(url),
                    json=body,
                    headers=self.headers,
                    cookies=self.cookies or None,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                last = str(exc)
                time.sleep(1.5)
                continue
            if r.status_code == 403 and "just a moment" in r.text[:600].lower():
                raise RelayError(
                    "Cloudflare challenge hit. This IP is blocked — run from your own "
                    "machine or tunnel: ssh -R 9999:id.jobstreet.com:443 user@host"
                )
            return r.status_code, r.text
        raise RelayError(f"Direct request failed: {last}")

    def get(self, url: str, **_) -> tuple[int, str]:
        return self._request("GET", url, None)

    def post(self, url: str, body: Optional[dict] = None, **_) -> tuple[int, str]:
        return self._request("POST", url, body)

    def supports_post(self) -> bool:
        return True
