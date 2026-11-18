"""Offline demo data; never imports facts into the user's actual profile."""

DEMO_JOBS = [
    {
        "external_id": "demo-br",
        "url": "https://careers.example.org/jobs/1",
        "company": "Demo BR",
        "title": "Senior Frontend",
        "description": "React role",
        "remote": True,
        "allowed_countries": ["BR"],
        "eligibility_evidence": "Remote Brazil",
        "status": "active",
        "requirements": {"technical": ["React", "Terraform"], "seniority": ["senior"]},
    },
    {
        "external_id": "demo-us",
        "url": "https://careers.example.org/jobs/2",
        "company": "Demo US",
        "title": "Backend",
        "description": "US residents only",
        "remote": True,
        "allowed_countries": ["US"],
        "eligibility_evidence": "US residents only",
        "requirements": {"technical": ["Python"]},
    },
    {
        "external_id": "demo-unknown",
        "url": "https://careers.example.org/jobs/3",
        "company": "Demo Unknown",
        "title": "Full Stack",
        "description": "Remote",
        "remote": True,
        "requirements": {"technical": ["React"]},
    },
]


def fixture_source() -> list[dict]:
    from job_hunter.infrastructure.db import utcnow

    return [
        {**job, "published_at": utcnow().isoformat(), "publication_basis": "synthetic_demo"}
        for job in DEMO_JOBS
    ]
