# jobstreet-reverse

Reverse-engineered toolkit + production scraper for **JobStreet / SEEK Asia**
(`id.jobstreet.com`, `my.jobstreet.com`, `sg.jobstreet.com`, `ph.jobstreet.com`,
`th.jobsdb.com`, `hk.jobsdb.com`).

Everything here was derived from the shipped frontend bundle and live probing —
no private API keys, no account required for the read paths.

```
pip install requests
python3 jsk/scrape.py "data analyst" --where Jakarta --days 7 --details
```

---

## What works from anywhere (no account, no setup)

JobStreet sits behind a Cloudflare Managed Challenge. Datacenter IPs (any normal
VPS) get a 403 interstitial on **every** request — TLS fingerprint, HTTP/2 and
residential-proxy tricks all failed. The one path that works is a third-party
fetcher, `api.keenable.ai/v1/fetch/public`, which is GET-only.

| Capability | Endpoint | Status |
|---|---|---|
| Job search (full filter set) | `GET /api/jobsearch/v5/search` | ✅ |
| Result count only | same, `pageSize=0` | ✅ |
| Job detail (SSR → text) | `GET /id/job/<id>` | ✅ |
| Company profile | `GET /companies/<slug>-<id>` | ✅ |
| 6 country domains | same API path | ✅ |

### The search API

```
GET https://id.jobstreet.com/api/jobsearch/v5/search
      ?keywords=data%20analyst
      &where=Jakarta
      &page=1
      &pageSize=25
```

| Param | Values |
|---|---|
| `keywords` | free text |
| `page` / `pageSize` | `1..30` / max **25** (relay truncates ~50 KB) |
| `where` | `Jakarta`, `Surabaya`, `Bandung`, … |
| `sortmode` | `KeywordRelevance` (default), `ListedDate` |
| `daterange` | `1` `3` `7` `14` `30` (days) |
| `worktype` | `242` full-time · `243` part-time · `244` contract · `245` casual |
| `workarrangement` | `1` on-site · `2` hybrid · `3` remote |
| `salaryrange` | `8000000-`, `-15000000`, `5000000-12000000` |
| `salarytype` | `monthly` · `annual` · `hourly` |
| `classification` / `subclassification` | numeric ids (`6281` = ICT) |
| `companyname` / `advertiserid` | company filters |
| `tags` | `applied` `applyStarted` `new` `sab` `seen` `viewed` |
| `include` | `facets` `suggestions` … |

Response envelope:

```json
{
  "data": [ { "id": "...", "title": "...", "companyName": "...",
              "salaryLabel": "...", "listingDate": "...",
              "classifications": [...], "locations": [...],
              "solMetadata": {...}, "tracking": "..." } ],
  "totalCount": 13428,
  "sortModes": [...],
  "solMetadata": { "requestToken": "...", "totalJobCount": 13428, "tags": {...} }
}
```

---

## The GraphQL layer (needs your session)

The real brain of the site is GraphQL at `POST /graphql`. It is fully mapped —
15 operations, 7 mutations — but **it is POST, and POST cannot cross the
Cloudflare wall from a blocked IP**, cookies or not.

```
POST https://id.jobstreet.com/graphql
X-Seek-Site: chalice
x-custom-features: application/features.seek.all+json
Cookie: sol_id, JobseekerSessionId, JobseekerVisitorId, appSession (JWE)
```

To use it, run the client from an IP Cloudflare trusts. The zero-config way is an
SSH tunnel that terminates on the target itself:

```bash
ssh -R 9999:id.jobstreet.com:443 you@your-vps
```

```python
from jsk import GraphQL
gql = GraphQL.from_cookie_file("cookies.json")   # points at https://localhost:9999
gql.viewer()
gql.save_job("95486039")
```

### Operations recovered from the bundle

**Queries** — `JobSearchV7`, `JobSearchV7Shadow`, `JobCountV7`, `JobCountV7Shadow`,
`GetDocumentUploadData`, `HasResumeBeenParsed`, `ListBrands`, `BrandingAssets`,
`IsImagePublished`, `MarqueeCompanies`.

**Mutations** — `CreateSavedJob` (`createSavedJob2`), `DeleteSavedJob`
(`deleteSavedJob2`), `AboutMeUpdateRole`, `AboutMeDeleteRole`,
`ConfirmProfileUpToDate`, `createBrand`, `updateBrand`.

**Ontology/autocomplete** — `getRoleTitle`, `getOrganisations`,
`getQualifications`, `getEducationProviders`, `getSpecReqs`, `trackSelected`,
`getProfileLocationSuggest`, `profileLocationTrackSelected`,
`getRightToWorkOptions`, `getClassificationOptions`.

The full 308-line `JobSearchV7` document (jobs, enrichment facets, location
suggestions, spelling correction, search context, metadata) is in
[`docs/query.graphql`](docs/query.graphql). Introspection is disabled server-side.

### Internal endpoints found in `window.SEEK_CONFIG`

```
http://jobsearch-api.int-cloud.seek.com.au/v5/search
http://candidate-graphql.int-cloud.seek.com.au/graphql
```

Both resolve into `*.ap-southeast-2.production.internal.seek.com` — AWS VPC
internal, unreachable from the internet. Recorded for completeness, not usable.

---

## Package layout

```
jsk/
  relay.py     KeenableRelay (GET-only, public) · DirectRelay (cookies/POST/tunnel)
  client.py    JobStreet — count(), search(), iter_jobs(), job_detail(), company()
  graphql.py   GraphQL — viewer(), search_count(), save_job(), unsave_job()
  scrape.py    CLI
docs/query.graphql   full JobSearchV7 document
examples/            runnable snippets
```

## Usage

```python
from jsk import JobStreet

js = JobStreet()                                  # id.jobstreet.com
js = JobStreet(domain="sg.jobstreet.com")          # any SEEK Asia domain

js.count("data analyst", where="Jakarta")          # 1450
jobs = js.search("data analyst", limit=100, where="Jakarta", days=7)

js.job_detail(jobs[0]["id"])                       # SSR page → text, salary, location
js.company("walden-global-services-168553709475634")
```

CLI:

```bash
python3 jsk/scrape.py "software engineer" --where Jakarta --days 3 --max 100 \
        --details --max-details 20 -o swe.json
python3 jsk/scrape.py "it" --count-only
```

## Known limits

- `pageSize` > 25 → relay truncation, parse failure.
- Pagination stops at ~30 pages (~450–750 jobs) regardless of `totalCount`.
- GraphQL POST, saved jobs, profile, and mutations require `DirectRelay`
  (your machine or an SSH tunnel).
- The relay returns **markdown**, not raw HTML — parse text, not DOM.
