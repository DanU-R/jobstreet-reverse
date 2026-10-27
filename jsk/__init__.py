"""jsk — JobStreet / SEEK Asia reverse-engineered toolkit.

Public surface:
    from jsk import JobStreet, Relay, GraphQL

    js = JobStreet()                 # uses Keenable relay (no auth needed)
    jobs = js.search("data analyst", where="Jakarta")

    # authenticated (needs cookies + a residential IP / SSH tunnel)
    gql = GraphQL.from_cookie_file("cookies.json")
    gql.query("{ viewer { firstName } }")
"""

from .relay import Relay, KeenableRelay, DirectRelay
from .client import JobStreet, JobStreetError
from .graphql import GraphQL, GraphQLError

__version__ = "1.0.0"
__all__ = [
    "JobStreet",
    "JobStreetError",
    "Relay",
    "KeenableRelay",
    "DirectRelay",
    "GraphQL",
    "GraphQLError",
]
