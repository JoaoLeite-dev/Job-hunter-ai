"""Read-only public API, fixed origin, bounded IO, and conservative normalization."""

import json
import re
import time
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from job_hunter.application.matching import canonicalize
from job_hunter.application.search_configuration import contains, normalized

ENDPOINT = "https://remotive.com/api/remote-jobs?category=software-dev"
MAX_BYTES = 10_000_000


class SourceError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_public_jobs() -> dict:
    request = Request(
        ENDPOINT,
        headers={
            "User-Agent": "JobHunterAI/0.1 (personal local reader)",
            "Accept": "application/json",
        },
    )
    try:
        deadline = time.monotonic() + 25
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            chunks, size = [], 0
            while chunk := response.read(64 * 1024):
                size += len(chunk)
                if size > MAX_BYTES or time.monotonic() > deadline:
                    raise SourceError("source_response_limit")
                chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        validate_payload(payload)
        return payload
    except (URLError, OSError, ValueError, TypeError):
        raise SourceError("source_unavailable") from None


def validate_payload(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise SourceError("source_invalid_payload")
    if len(payload["jobs"]) > 5000:
        raise SourceError("source_response_limit")


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "li", "br", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    if not isinstance(value, str) or len(value) > 250_000:
        raise ValueError("Invalid text")
    parser = PlainText()
    parser.feed(value)
    return "\n".join(
        " ".join(line.split()) for line in "".join(parser.parts).splitlines() if line.strip()
    )


def location_policy(value: str, description: str) -> dict:
    location = value.strip().casefold()
    # Region names represent the provider's hiring scope, not the candidate's location.
    brazil = bool(re.search(r"\b(brazil|brasil|latam|latin america|south america)\b", location))
    worldwide = location in {"worldwide", "anywhere", "global"}
    restricted = {
        "US": r"\b(usa|united states|us only)\b",
        "CA": r"\b(canada)\b",
        "EU": r"\b(europe|european union|eu only)\b",
        "GB": r"\b(uk|united kingdom)\b",
    }
    countries = (
        ["BR"]
        if brazil
        else ["WORLDWIDE"]
        if worldwide
        else [code for code, pattern in restricted.items() if re.search(pattern, location)]
    )
    conflict = bool(
        re.search(
            r"\b(us residents only|must (?:reside|be based|be located) in "
            r"(?:the )?(?:us|usa|united states)|us work authorization|security clearance)\b",
            description.casefold(),
        )
    )
    if conflict and (brazil or worldwide):
        countries = []
    return {
        "allowed_countries": countries,
        "eligibility_evidence": f"Remotive: candidate_required_location = {value}"
        if countries
        else "",
        "work_authorization_required": conflict,
    }


SKILLS = {
    "react": "React",
    "react js": "React",
    "react.js": "React",
    "react native": "React Native",
    "expo": "Expo",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "node.js": "Node.js",
    "python": "Python",
    "java": "Java",
    "docker": "Docker",
    "aws": "AWS",
    "terraform": "Terraform",
    "postgresql": "PostgreSQL",
    "git": "Git",
    "next.js": "Next.js",
    "sql": "SQL",
    "css": "CSS",
    "html": "HTML",
    "angular": "Angular",
    "vue.js": "Vue.js",
}


def normalize_jobs(
    payload: dict, roles: str, fetched_at: str, *, exclude_junior=True
) -> list[dict]:
    validate_payload(payload)
    terms = [normalized(x) for x in roles.split(",") if x.strip()]
    if not terms:
        raise SourceError("source_roles_missing")
    records = []
    for item in payload["jobs"]:
        try:
            title = plain_text(item["title"])
            title_search = normalized(title)
            if not any(contains(title_search, term) for term in terms) or (
                exclude_junior
                and re.search(r"\b(junior|jr|intern|internship|trainee|est[aá]gio)\b", title_search)
            ):
                continue
            company = plain_text(item["company_name"])
            description = plain_text(item["description"])
            url = canonicalize(item["url"])
            if urlsplit(url).hostname != "remotive.com" or not title or not company:
                raise ValueError("Invalid source identity")
            if len(title) > 250 or len(company) > 250:
                raise ValueError("Source field too long")
            external_id = str(item["id"])
            if not external_id.isdecimal() or len(external_id) > 100:
                raise ValueError("Invalid ID")
            location = item.get("candidate_required_location", "")
            if not isinstance(location, str) or len(location) > 1000:
                raise ValueError("Invalid location")
            tags = item.get("tags", [])
            if not isinstance(tags, list):
                raise ValueError("Invalid tags")
            skills = sorted(
                {
                    SKILLS[t.strip().casefold()]
                    for t in tags
                    if isinstance(t, str) and t.strip().casefold() in SKILLS
                }
            )
            records.append(
                {
                    "external_id": external_id,
                    "url": url,
                    "company": company,
                    "title": title,
                    "description": description,
                    "status": "active",
                    "remote": True,
                    **location_policy(location, description),
                    "requirements": {"technical": skills},
                    "source_name": "Remotive",
                    "source_url": url,
                    "source_location": location,
                    "published_at": str(item.get("publication_date", ""))[:100],
                    "observed_at": fetched_at,
                    "requirement_basis": "provider_tags",
                    "score_notice": (
                        "Pontuação preliminar por tags da fonte e fatos confirmados; "
                        "requisitos obrigatórios ainda não analisados por IA."
                    ),
                }
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            # An invalid record never prevents other provider records from being read.
            continue
    return records
