"""High-level JobStreet client — the public, unauthenticated surface.

Everything here works with just the Keenable relay (no cookies, no tunnel):

    js = JobStreet()
    total = js.count("data analyst", where="Jakarta")
    for job in js.iter_jobs("data analyst", where="Jakarta", days=7):
        ...
    detail = js.job_detail(job["id"])     # SSR HTML → text + parsed bits

Same API on all domains: id/my/sg/ph.jobstreet.com, th/hk.jobsdb.com.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Iterator, List, Optional

from .relay import DirectRelay, KeenableRelay, Relay, RelayError

# --- enums verified against the shipped bundle (js/main.js module 85829) ---
WORK_TYPES = {"full_time": "242", "part_time": "243", "contract": "244", "casual": "245"}
WORK_ARRANGEMENTS = {"on_site": "1", "hybrid": "2", "remote": "3"}
SORT_MODES = {"relevance": "KeywordRelevance", "date": "ListedDate"}
SALARY_PERIODS = ("monthly", "annual", "hourly")

VALID_DOMAINS = (
    "id.jobstreet.com",
    "my.jobstreet.com",
    "sg.jobstreet.com",
    "ph.jobstreet.com",
    "th.jobsdb.com",
    "hk.jobsdb.com",
)

DEFAULT_PAGE_SIZE = 25   # >25 blows the relay's ~50 KB response cap
MAX_PAGES = 30           # JobStreet itself stops serving beyond ~30


class JobStreetError(RuntimeError):
    pass


class JobStreet:
    def __init__(
        self,
        domain: str = "id.jobstreet.com",
        relay: Optional[Relay] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        delay: float = 0.8,
    ):
        if domain not in VALID_DOMAINS:
            raise JobStreetError(f"unknown domain {domain!r}; one of {VALID_DOMAINS}")
        self.domain = domain
        self.relay = relay or KeenableRelay()
        self.page_size = min(page_size, DEFAULT_PAGE_SIZE)
        self.delay = delay

    # ---------- transport helpers ----------

    def _get_json(self, url: str) -> Dict[str, Any]:
        _, text = self.relay.get(url)
        # relay delivers a JSON string; occasionally double-encoded
        try:
            data = json.loads(text, strict=False)
        except json.JSONDecodeError:
            try:
                data = json.loads(json.loads(text, strict=False), strict=False)
            except Exception as exc:
                raise JobStreetError(f"unparsable response from {url[:120]}") from exc
        if isinstance(data, dict) and data.get("error"):
            raise JobStreetError(f"upstream error: {data['error']}")
        return data

    def _search_url(self, page: int, params: Dict[str, Any]) -> str:
        qs = "&".join(
            f"{k}={str(v).replace(' ', '%20')}"
            for k, v in params.items()
            if v is not None and v != ""
        )
        return f"https://{self.domain}/api/jobsearch/v5/search?{qs}&page={page}&pageSize={self.page_size}"

    # ---------- filters ----------

    @staticmethod
    def build_filters(
        *,
        where: Optional[str] = None,
        days: Optional[int] = None,
        sort: Optional[str] = None,
        work_type: Optional[str] = None,
        work_arrangement: Optional[str] = None,
        salary_min: Optional[int] = None,
        salary_max: Optional[int] = None,
        salary_type: str = "monthly",
        classification: Optional[str] = None,
        subclassification: Optional[str] = None,
        company: Optional[str] = None,
        advertiser_id: Optional[str] = None,
        tags: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """Map friendly names onto JobStreet's raw query params.

        work_type: full_time|part_time|contract|casual (or a raw code like 242)
        work_arrangement: on_site|hybrid|remote (or a raw code like 1)
        sort: relevance|date (or raw KeywordRelevance/ListedDate)
        salary_min/max: rupiah integers (salarytype must be monthly|annual|hourly)
        """
        f: Dict[str, Any] = {}
        if where:
            f["where"] = where
        if days:
            f["daterange"] = days
        if sort:
            f["sortmode"] = SORT_MODES.get(sort, sort)
        if work_type:
            f["worktype"] = WORK_TYPES.get(work_type, work_type)
        if work_arrangement:
            f["workarrangement"] = WORK_ARRANGEMENTS.get(work_arrangement, work_arrangement)
        if salary_min is not None or salary_max is not None:
            lo = str(salary_min or "")
            hi = str(salary_max or "")
            f["salaryrange"] = f"{lo}-{hi}"
            f["salarytype"] = salary_type
        if classification:
            f["classification"] = classification
        if subclassification:
            f["subclassification"] = subclassification
        if company:
            f["companyname"] = company
        if advertiser_id:
            f["advertiserid"] = advertiser_id
        if tags:
            f["tags"] = tags
        f.update({k: v for k, v in extra.items()})
        return f

    # ---------- public API ----------

    def count(self, keywords: str, **filters) -> int:
        """Result count only (pageSize=0 — one round trip, zero job payload)."""
        p = dict(keywords=keywords, pageSize=0, **self.build_filters(**filters))
        return int(self._get_json(self._search_url(1, p)).get("totalCount") or 0)

    def search_page(self, keywords: str, page: int = 1, **filters) -> Dict[str, Any]:
        """One page of results plus envelope metadata (totalCount, sortModes, ...)."""
        p = dict(keywords=keywords, **self.build_filters(**filters))
        return self._get_json(self._search_url(page, p))

    def search(self, keywords: str, limit: int = 100, **filters) -> List[Dict[str, Any]]:
        """Collect up to `limit` jobs across pages."""
        return list(self.iter_jobs(keywords, limit=limit, **filters))

    def iter_jobs(
        self, keywords: str, limit: Optional[int] = None, **filters
    ) -> Iterator[Dict[str, Any]]:
        """Page through results until exhausted, limit reached, or page 30."""
        got = 0
        for page in range(1, MAX_PAGES + 1):
            data = self.search_page(keywords, page=page, **filters)
            jobs = data.get("data") or []
            if not jobs:
                return
            for job in jobs:
                yield job
                got += 1
                if limit is not None and got >= limit:
                    return
            if len(jobs) < self.page_size:
                return
            time.sleep(self.delay)

    def job_detail(self, job_id: str | int) -> Dict[str, Any]:
        """Fetch a job's SSR page and parse what we can out of it.

        Keenable returns MARKDOWN, not raw HTML — the title therefore comes
        from relay metadata, not a <title> regex.
        Returns: id, page_title, salary, posted, work_types, location, text.
        """
        url = f"https://{self.domain}/id/job/{job_id}"
        page = self.relay.get_full(url)
        html = page.get("content") or ""
        title = (page.get("title") or "").strip()

        detail: Dict[str, Any] = {"id": str(job_id), "url": url, "page_title": title}
        if not title:
            m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
            detail["page_title"] = m.group(1).strip() if m else ""

        body = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.I)
        body = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", body, flags=re.I)
        body = re.sub(r"<[^>]+>", "\n", body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        detail["text"] = body

        m = re.search(r"Rp[\s\u00A0]*[\d.,]+(?:\s*[-–]\s*Rp?[\s\u00A0]*[\d.,]+)?(?:\s*(?:per|/)\s*\w+)?", body)
        detail["salary"] = m.group(0).strip() if m else ""

        m = re.search(r"(?:Posted|Dipasang)[:\s]+([^\n]+)", body, re.I)
        detail["posted"] = m.group(1).strip() if m else ""

        types = re.findall(r"(?:Full.time|Part.time|Contract|Casual|Kontrak)", body, re.I)
        detail["work_types"] = sorted({t.strip() for t in types})

        m = re.search(r"\s(?:in|di)\s+(.+?)(?:\s*-\s*Jobstreet.*)?$", detail["page_title"])
        detail["location"] = m.group(1).strip() if m else ""

        return detail

    def company(self, company_slug: str) -> Dict[str, Any]:
        """Fetch a company profile SSR page (/companies/<slug>-<id>)."""
        url = f"https://{self.domain}/companies/{company_slug}"
        page = self.relay.get_full(url)
        html = page.get("content") or ""
        return {
            "slug": company_slug,
            "url": url,
            "page_title": (page.get("title") or "").strip(),
            "raw_len": len(html),
        }

    def suggest_count(self, keywords: str, **filters) -> int:
        """Alias kept for readability at call sites."""
        return self.count(keywords, **filters)
