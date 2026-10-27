"""Minimal search + detail — no account needed."""

from jsk import JobStreet

js = JobStreet()

print("count:", js.count("data analyst", where="Jakarta"))

jobs = js.search("data analyst", limit=5, where="Jakarta", days=7)
for j in jobs:
    print(f"{j['id']}  {j['title'][:45]:45s}  {j.get('companyName','')[:28]}")

detail = js.job_detail(jobs[0]["id"])
print("\n--- detail ---")
print("title   :", detail["page_title"])
print("location:", detail["location"])
print("text    :", detail["text"][:300])
