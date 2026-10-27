#!/usr/bin/env python3
"""JobStreet scraper CLI — search + optional detail enrichment.

Examples:
    python3 jsk/scrape.py "data analyst" --where Jakarta --days 7
    python3 jsk/scrape.py "python" --max 100 --details --max-details 20
    python3 jsk/scrape.py "it" --count-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jsk import JobStreet, JobStreetError


def main() -> int:
    ap = argparse.ArgumentParser(description="JobStreet/SEEK Asia scraper")
    ap.add_argument("keywords")
    ap.add_argument("--where", help="location, e.g. Jakarta")
    ap.add_argument("--max", type=int, default=50, help="max jobs (default 50)")
    ap.add_argument("--days", type=int, help="posted within N days: 1/3/7/14/30")
    ap.add_argument("--sort", choices=["relevance", "date"], default=None)
    ap.add_argument("--worktype", choices=["full_time", "part_time", "contract", "casual"])
    ap.add_argument("--arrangement", choices=["on_site", "hybrid", "remote"])
    ap.add_argument("--salary-min", type=int, help="minimum monthly salary (Rp)")
    ap.add_argument("--salary-max", type=int)
    ap.add_argument("--classification", help="classification id, e.g. 6281 = ICT")
    ap.add_argument("--company", help="company name filter")
    ap.add_argument("--domain", default="id.jobstreet.com",
                    choices=["id.jobstreet.com", "my.jobstreet.com", "sg.jobstreet.com",
                             "ph.jobstreet.com", "th.jobsdb.com", "hk.jobsdb.com"])
    ap.add_argument("--details", action="store_true", help="fetch SSR detail per job")
    ap.add_argument("--max-details", type=int, default=10)
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("-o", "--output", help="output .json path")
    args = ap.parse_args()

    js = JobStreet(domain=args.domain)
    filters = dict(
        where=args.where, days=args.days, sort=args.sort,
        work_type=args.worktype, work_arrangement=args.arrangement,
        salary_min=args.salary_min, salary_max=args.salary_max,
        classification=args.classification, company=args.company,
    )

    try:
        if args.count_only:
            n = js.count(args.keywords, **filters)
            print(f"{n} matching jobs")
            return 0

        print(f"Scraping {args.domain}: {args.keywords!r} (max {args.max})")
        jobs = js.search(args.keywords, limit=args.max, **filters)
        print(f"  search: {len(jobs)} jobs")

        if args.details:
            print(f"  details: {min(len(jobs), args.max_details)} pages")
            enriched = []
            for i, job in enumerate(jobs[: args.max_details]):
                try:
                    detail = js.job_detail(job["id"])
                except Exception as exc:
                    print(f"    #{job['id']} failed: {exc}")
                    detail = {}
                enriched.append({**job, "detail": detail})
                print(f"    [{i+1}] #{job['id']} {job.get('title','')[:50]}")
                time.sleep(0.5)
            rest = [{**j, "detail": None} for j in jobs[args.max_details:]]
            jobs = enriched + rest

        out = args.output or f"jobs_{args.keywords.replace(' ', '_')}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump({
                "query": args.keywords,
                "filters": {k: v for k, v in filters.items() if v},
                "domain": args.domain,
                "count": len(jobs),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "jobs": jobs,
            }, f, ensure_ascii=False, indent=1)
        print(f"Saved {len(jobs)} jobs → {out}")
        return 0

    except JobStreetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
