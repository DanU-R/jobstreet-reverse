"""Authenticated GraphQL — run from your machine or via SSH tunnel.

    ssh -R 9999:id.jobstreet.com:443 you@your-vps     # on the VPS side
    python3 examples/graphql.py cookies.json

`cookies.json` is a browser export (list of {name, value, ...}).
"""

import json
import sys

from jsk import GraphQL

if len(sys.argv) < 2:
    raise SystemExit("usage: python3 examples/graphql.py cookies.json")

gql = GraphQL.from_cookie_file(sys.argv[1])

print("viewer:", json.dumps(gql.viewer(), ensure_ascii=False))

# JobSearchV7 count via GraphQL (params built by hand; see docs/query.graphql)
try:
    n = gql.search_count({
        "searchIntent": {"locale": "id-ID", "text": "data analyst", "sort": "score"},
        "searchContext": {"brand": "jobstreet", "channel": "web", "source": "FE_SERP"},
        "responseConfig": {"page": 1, "pageSize": 1, "results": ["count"]},
    })
    print("jobSearchV7 count:", n)
except Exception as exc:
    print("jobSearchV7 failed:", exc)

# saved-job mutations need a real job id you own
# print(gql.save_job("95486039"))
