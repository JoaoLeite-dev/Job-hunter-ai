"""Bounded HTML readers for public Brazilian listings. No login or challenge bypass."""

import re
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from job_hunter.application.matching import canonicalize
from job_hunter.application.search_configuration import contains, normalized
from job_hunter.infrastructure.remotive import SKILLS, NoRedirect, SourceError

ORIGINS = {"infojobs": "https://www.infojobs.com.br", "vagas": "https://www.vagas.com.br"}
NAMES = {"infojobs": "InfoJobs", "vagas": "Vagas.com"}
USER_AGENT = "JobHunterAI/0.1 (personal local job reader)"


def robots_allow(raw, url):
    groups, agents, rules = [], [], []
    for line in raw.decode("utf-8", "replace").splitlines():
        key, separator, value = line.split("#", 1)[0].partition(":")
        if not separator:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in {"allow", "disallow"} and agents and value:
            rules.append((key == "allow", value))
    if agents:
        groups.append((agents, rules))
    if not groups:
        raise SourceError("source_robots_unverifiable")
    matches = [
        (len(agent) if agent != "*" else 0, group_rules)
        for group_agents, group_rules in groups
        for agent in group_agents
        if agent == "*" or agent in USER_AGENT.lower()
    ]
    specificity = max((length for length, _ in matches), default=-1)
    parts = urlsplit(url)
    target = parts.path + ("?" + parts.query if parts.query else "")
    decisions = []
    for length, group_rules in matches:
        if length != specificity:
            continue
        for allow, pattern in group_rules:
            expression = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
            if re.match("^" + expression + ("$" if pattern.endswith("$") else ""), target):
                decisions.append((len(pattern.replace("*", "").rstrip("$")), allow))
    return max(decisions, default=(0, True))[1]


def queries_for(config):
    queries, seen = [], set()
    for value in config["title_terms"]:
        identity = normalized(value).replace(" ", "")
        if identity not in seen:
            queries.append(value)
            seen.add(identity)
        if len(queries) == 3:
            break
    return queries


def search_url(source, term):
    if source == "infojobs":
        return ORIGINS[source] + "/empregos.aspx?" + urlencode({"palabra": term})
    return ORIGINS[source] + "/vagas-de-" + quote(normalized(term).replace(" ", "-"), safe="")


def read_public(url, deadline, maximum=2_500_000):
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError("source_timeout")
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"})
        with build_opener(NoRedirect()).open(request, timeout=min(10, remaining)) as response:
            chunks, size = [], 0
            while chunk := response.read(64 * 1024):
                size += len(chunk)
                if size > maximum or time.monotonic() >= deadline:
                    raise SourceError("source_response_limit")
                chunks.append(chunk)
            return b"".join(chunks)
    except HTTPError as error:
        code = "source_access_blocked" if error.code in {401, 403, 429} else "source_http_error"
        raise SourceError(code) from None
    except (URLError, OSError):
        raise SourceError("source_unavailable") from None


def text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def source_date(value, pattern):
    try:
        return (
            datetime.strptime(value, pattern)
            .replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
            .isoformat()
        )
    except (ValueError, TypeError):
        return ""


def listing_record(
    source, identity, href, title, company, description, published, location, modality=""
):
    url = canonicalize(urljoin(ORIGINS[source], href))
    if urlsplit(url).netloc != urlsplit(ORIGINS[source]).netloc:
        raise ValueError("Foreign listing link")
    if not (
        urlsplit(url).path.startswith("/vaga-")
        if source == "infojobs"
        else re.match(r"/vagas/v\d+", urlsplit(url).path)
    ):
        raise ValueError("Not a public job link")
    if not identity.isdecimal() or not title or len(title) > 250 or len(company) > 250:
        raise ValueError("Invalid listing identity")
    content = normalized(modality)
    remote = (
        True
        if any(
            contains(content, word) for word in ["home office", "homeoffice", "remoto", "remote"]
        )
        else False
        if contains(content, "presencial")
        else None
    )
    if contains(content, "hibrido"):
        remote = False
    if remote and contains(content, "presencial"):
        remote = None
    # Do not infer residency from the board domain. Brazilian state codes are evidence.
    brazil = (
        bool(
            re.search(
                r"(?:/| - |, )\s*(?:AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|"
                r"RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b",
                location,
                re.I,
            )
        )
        or normalized(location) == "brasil"
    )
    return {
        "external_id": identity,
        "url": url,
        "title": title,
        "company": company or "Empresa não informada pela fonte",
        "description": description[:250_000],
        "published_at": published,
        "publication_basis": "listing_publication_field",
        "status": "active",
        "remote": remote,
        "allowed_countries": ["BR"] if brazil else [],
        "source_location": "Brazil" if brazil else location,
        "job_location": location,
        "eligibility_evidence": f"{NAMES[source]}: região {location}; modalidade explícita"
        if brazil and remote
        else "",
        "source_name": NAMES[source],
        "source_url": url,
        "requirements": {
            "technical": sorted(
                {skill for key, skill in SKILLS.items() if contains(description, key)}
            )
        },
        "requirement_basis": "listing_excerpt",
        "description_complete": False,
        "score_notice": (
            "Pontuação preliminar pelo resumo público. "
            "A descrição completa e requisitos obrigatórios precisam de revisão."
        ),
    }


def parse_listings(source, raw):
    soup = BeautifulSoup(raw, "html.parser")
    for node in soup.select("script, style, svg, [onclick][data-bs-toggle]"):
        node.decompose()
    records = []
    cards = soup.select(".js_cardLink[data-id]") if source == "infojobs" else soup.select("li.vaga")
    if not cards and not any(
        word in normalized(text(soup)) for word in ["nenhuma vaga", "nao encontramos", "0 vagas"]
    ):
        raise SourceError("source_layout_changed")
    for card in cards[:30]:
        try:
            if source == "infojobs":
                title = text(card.select_one(".js_vacancyTitle"))
                company = text(card.select_one("a[href*='/empresa-']"))
                node = card.select_one(".js_date[data-value]")
                published = source_date(
                    node.get("data-value", "") if node else "", "%Y/%m/%d %H:%M:%S"
                )
                identity, href = card.get("data-id", ""), card.get("data-href", "")
                location = text(card.select_one("div.mb-8"))
                modality = text(card.select_one(".d-inline-flex.flex-wrap.mb-8"))
            else:
                link = card.select_one(".link-detalhes-vaga")
                if not link:
                    continue
                title, company = text(link), text(card.select_one(".emprVaga"))
                published = source_date(text(card.select_one(".data-publicacao")), "%d/%m/%Y")
                identity, href = link.get("data-id-vaga", ""), link.get("href", "")
                location = text(card.select_one(".vaga-local"))
                modality = text(card.select_one(".modalidade, .tipo-trabalho"))
            records.append(
                listing_record(
                    source,
                    identity,
                    href,
                    title,
                    company,
                    text(card),
                    published,
                    location,
                    modality,
                )
            )
        except (TypeError, ValueError, AttributeError):
            continue
    return records


def fetch_board(source, config):
    if source not in ORIGINS:
        raise SourceError("unsupported_source")
    deadline = time.monotonic() + 30
    robots = read_public(ORIGINS[source] + "/robots.txt", deadline, 250_000)
    records, seen = [], set()
    queries = queries_for(config)
    for index, term in enumerate(queries):
        url = search_url(source, term)
        if not robots_allow(robots, url):
            raise SourceError("source_robots_disallowed")
        if index:
            time.sleep(1)
        html = read_public(url, deadline)
        for item in parse_listings(source, html):
            if item["external_id"] not in seen:
                records.append(item)
                seen.add(item["external_id"])
    return {"jobs": records, "normalized": True, "queries": queries}
