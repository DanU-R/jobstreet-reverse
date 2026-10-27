"""Authenticated GraphQL client for id.jobstreet.com.

Why it exists: the frontend's real brain is GraphQL (jobSearchV7, saved jobs,
profile), but POST /graphql sits behind the same Cloudflare wall — from a
datacenter IP you get the challenge regardless of cookies. So this client
demands a DirectRelay: your own machine, or an SSH tunnel.

    # on your laptop (or via  ssh -R 9999:id.jobstreet.com:443 you@host)
    from jsk import GraphQL
    gql = GraphQL.from_cookie_file("cookies.json")
    gql.query("{ viewer { firstName lastName } }")

Operations below are copied verbatim from the shipped bundle (main.js);
docs/query.graphql holds the full 308-line jobSearchV7.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .relay import DirectRelay, Relay, RelayError

GRAPHQL_PATH = "/graphql"
REQUIRED_HEADERS = {
    "X-Seek-Site": "chalice",
    "x-custom-features": "application/features.seek.all+json",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ---- operations extracted from the bundle -------------------------------

VIEWER = """
query Viewer {
  viewer {
    __typename
    ... on Candidate {
      id
      firstName
      lastName
      email
    }
  }
}
"""

# `count` variant of JobSearchV7 — smallest useful search query.
SEARCH_COUNT = """
query JobCountV7($params: JobSearchV7QueryInput!) {
  jobSearchV7(params: $params) {
    results {
      pagination { resultCount }
    }
  }
}
"""

CREATE_SAVED_JOB = """
mutation CreateSavedJob($input: CreateSavedJobInput!, $locale: Locale) {
  createSavedJob2(input: $input) {
    __typename
    ... on CreateSavedJobSuccess { id }
    ... on CreateSavedJobFailure {
      errors { message(locale: $locale) }
    }
  }
}
"""

DELETE_SAVED_JOB = """
mutation DeleteSavedJob($input: DeleteSavedJobInput!, $locale: Locale) {
  deleteSavedJob2(input: $input) {
    __typename
    ... on DeleteSavedJobSuccess { id }
    ... on DeleteSavedJobFailure {
      errors { message(locale: $locale) }
    }
  }
}
"""


class GraphQLError(RuntimeError):
    pass


class GraphQL:
    def __init__(self, relay: Optional[Relay] = None, domain: str = "id.jobstreet.com"):
        if relay is None:
            relay = DirectRelay(headers=dict(REQUIRED_HEADERS))
        if not relay.supports_post():
            raise GraphQLError(
                "GraphQL needs POST. Provide DirectRelay (cookies, unblocked IP, "
                "or an SSH tunnel) — Keenable cannot deliver POST bodies."
            )
        self.relay = relay
        self.domain = domain

    @classmethod
    def from_cookie_file(cls, path: str, base_override: Optional[str] = None, **kw) -> "GraphQL":
        relay = DirectRelay(
            cookies=DirectRelay.from_cookie_file(path).cookies,
            headers=dict(REQUIRED_HEADERS),
            base_override=base_override or f"https://localhost:9999",
            **kw,
        )
        return cls(relay=relay)

    def query(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        operation_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {"query": query}
        if variables is not None:
            body["variables"] = variables
        if operation_name:
            body["operationName"] = operation_name

        status, text = self.relay.post(f"https://{self.domain}{GRAPHQL_PATH}", body=body)
        if status != 200:
            raise GraphQLError(f"HTTP {status}: {text[:300]}")
        try:
            payload = json.loads(text, strict=False)
        except json.JSONDecodeError as exc:
            raise GraphQLError(f"non-JSON response: {text[:300]}") from exc
        if payload.get("errors"):
            raise GraphQLError(json.dumps(payload["errors"], ensure_ascii=False)[:500])
        return payload.get("data") or payload

    # ---- shortcuts ----

    def viewer(self) -> Dict[str, Any]:
        return self.query(VIEWER)

    def search_count(self, params: Dict[str, Any]) -> int:
        data = self.query(SEARCH_COUNT, {"params": params})
        return int(data["jobSearchV7"]["results"]["pagination"]["resultCount"])

    def save_job(self, job_id: str | int, locale: str = "id-ID") -> Dict[str, Any]:
        return self.query(
            CREATE_SAVED_JOB,
            {"input": {"jobId": str(job_id)}, "locale": locale},
            operation_name="CreateSavedJob",
        )

    def unsave_job(self, job_id: str | int, locale: str = "id-ID") -> Dict[str, Any]:
        return self.query(
            DELETE_SAVED_JOB,
            {"input": {"jobId": str(job_id)}, "locale": locale},
            operation_name="DeleteSavedJob",
        )
