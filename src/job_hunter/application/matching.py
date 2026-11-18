from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class Fact:
    id: str
    category: str
    claim: str
    verified: bool


def canonicalize(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Only public HTTPS source URLs are accepted")
    host = parts.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise ValueError("Local source URLs are not accepted")
    try:
        address = ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private source URLs are not accepted")
    if parts.port not in {None, 443}:
        raise ValueError("Only standard HTTPS ports are accepted")
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")]
    return urlunsplit(
        ("https", parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(query)), "")
    )


def eligibility(job: dict) -> dict:
    # Only normalized connector fields count as evidence, never model instructions.
    if job.get("status") == "expired":
        return {"status": "blocked", "reason": "expired"}
    if job.get("remote") is False:
        return {"status": "blocked", "reason": "onsite"}
    countries = job.get("allowed_countries", [])
    if countries and "BR" not in countries and "WORLDWIDE" not in countries:
        return {"status": "blocked", "reason": "residency_restriction"}
    if job.get("work_authorization_required"):
        return {"status": "needs_review", "reason": "work_authorization_unconfirmed"}
    if (
        job.get("remote") is True
        and job.get("eligibility_evidence")
        and ("BR" in countries or "WORLDWIDE" in countries)
    ):
        return {"status": "eligible", "reason": job["eligibility_evidence"]}
    return {"status": "needs_review", "reason": "insufficient_evidence"}


WEIGHTS = {"technical": 40, "seniority": 20, "domain": 15, "location": 15, "preferred": 10}


def score(job: dict, facts: list[Fact]) -> dict:
    gate = eligibility(job)
    evidence = []
    points = 15.0 if gate["status"] == "eligible" else 0.0
    for category, weight in WEIGHTS.items():
        if category == "location":
            continue
        requirements = job.get("requirements", {}).get(category, [])
        for requirement in requirements:
            matches = [
                f.id
                for f in facts
                if f.verified
                and f.category == category
                and f.claim.casefold() == requirement.casefold()
            ]
            evidence.append(
                {
                    "requirement": requirement,
                    "category": category,
                    "status": "met" if matches else "unknown",
                    "evidence_fact_ids": matches,
                    "explanation": "verified exact fact" if matches else "no verified evidence",
                }
            )
            if matches:
                points += weight / len(requirements)
    return {
        "score": round(points),
        "hard_gate": gate["status"] != "eligible",
        "eligibility": gate,
        "requirements": evidence,
        "model_version": "deterministic-v1",
    }
