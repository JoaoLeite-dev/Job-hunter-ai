"""Shared search semantics for manual runs, scheduler and cache-only preview."""

import re
import unicodedata

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from job_hunter.application.matching import eligibility
from job_hunter.application.publication import is_recent
from job_hunter.infrastructure.db import AuditEvent, SearchConfiguration

MARKETS = {"brazil", "international", "unknown"}
CATALOG = [
    {
        "id": "remotive",
        "name": "Remotive",
        "description": "API pública de vagas remotas; categoria desenvolvimento",
        "url": "https://remotive.com",
        "minimum_interval_hours": 6,
    }
]
CATALOG += [
    {
        "id": "infojobs",
        "name": "InfoJobs",
        "description": "Coleta HTML pública; primeira página de até 3 cargos por ciclo",
        "url": "https://www.infojobs.com.br",
        "minimum_interval_hours": 6,
    },
    {
        "id": "vagas",
        "name": "Vagas.com",
        "description": "Coleta HTML pública; primeira página de até 3 cargos por ciclo",
        "url": "https://www.vagas.com.br",
        "minimum_interval_hours": 6,
    },
    {
        "id": "linkedin",
        "name": "LinkedIn — publicações",
        "description": "Consulta assistida. Coleta automática requer autorização do LinkedIn.",
        "url": "https://www.linkedin.com/search/results/content/",
        "automated": False,
    },
    {
        "id": "indeed",
        "name": "Indeed",
        "description": "Consulta assistida. O acesso automático retornou HTTP 403; não conectado.",
        "url": "https://br.indeed.com/jobs",
        "automated": False,
    },
    {
        "id": "catho",
        "name": "Catho",
        "description": "Consulta assistida. O acesso automático retornou HTTP 403; não conectado.",
        "url": "https://www.catho.com.br/vagas/",
        "automated": False,
    },
    {
        "id": "gupy",
        "name": "Gupy",
        "description": "Consulta assistida; a API documentada requer token da empresa.",
        "url": "https://portal.gupy.io",
        "automated": False,
    },
    {
        "id": "trabalhabrasil",
        "name": "Trabalha Brasil",
        "description": "Consulta assistida. A listagem consultada não informou datas suficientes.",
        "url": "https://www.trabalhabrasil.com.br",
        "automated": False,
    },
]
AUTOMATED_SOURCES = {"remotive", "infojobs", "vagas"}


class ConfigurationError(ValueError):
    pass


class ConfigurationConflict(ConfigurationError):
    pass


def normalized(value):
    value = "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)
    )
    return " ".join(re.sub(r"[-_/]+", " ", value).split())


def contains(text, term):
    return (
        re.search(r"(?<!\w)" + re.escape(normalized(term)) + r"(?!\w)", normalized(text))
        is not None
    )


def market_for(job):
    """Hiring scope, never inferred employer domicile or candidate eligibility."""
    location = normalized(job.get("source_location", ""))
    if not location:
        return "unknown"
    if re.fullmatch(r"(?:remote[ ,:]+)?(?:brazil|brasil)(?:[ ,:]+remote)?", location):
        return "brazil"
    if any(
        contains(location, term)
        for term in [
            "worldwide",
            "anywhere",
            "global",
            "latam",
            "latin america",
            "south america",
            "usa",
            "united states",
            "canada",
            "europe",
            "uk",
            "united kingdom",
            "apac",
            "australia",
            "mexico",
            "germany",
            "portugal",
            "spain",
            "france",
            "india",
        ]
    ):
        return "international"
    return "unknown"


def defaults(settings):
    return {
        "enabled": True,
        "sources": ["remotive"],
        "title_terms": [x.strip() for x in settings.discovery_roles.split(",") if x.strip()],
        "keywords": [],
        "excluded_keywords": [],
        "excluded_titles": ["junior", "jr", "intern", "internship", "trainee", "estágio"],
        "keyword_mode": "any",
        "keyword_scope": "title_description",
        "markets": ["brazil", "international", "unknown"],
        "brazil_keywords": [],
        "international_keywords": [],
        "locations": [],
        "eligible_only": False,
    }


def validate_config(value, settings):
    expected = defaults(settings)
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ConfigurationError("invalid_configuration_fields")
    result = {}
    for key, sample in expected.items():
        actual = value[key]
        if isinstance(sample, bool):
            if type(actual) is not bool:
                raise ConfigurationError("invalid_boolean")
            result[key] = actual
        elif isinstance(sample, list):
            if not isinstance(actual, list) or len(actual) > 40:
                raise ConfigurationError("invalid_terms")
            cleaned = []
            for term in actual:
                if (
                    not isinstance(term, str)
                    or not term.strip()
                    or len(term) > 80
                    or any(ord(c) < 32 for c in term)
                ):
                    raise ConfigurationError("invalid_term")
                if normalized(term) not in {normalized(t) for t in cleaned}:
                    cleaned.append(term.strip())
            result[key] = cleaned
        else:
            result[key] = actual
    if not result["title_terms"] or not result["markets"]:
        raise ConfigurationError("titles_and_markets_required")
    if not set(result["sources"]) <= AUTOMATED_SOURCES or not set(result["markets"]) <= MARKETS:
        raise ConfigurationError("unsupported_source_or_market")
    if result["keyword_mode"] not in ("any", "all") or result["keyword_scope"] not in (
        "title",
        "title_description",
    ):
        raise ConfigurationError("invalid_matching_mode")
    return result


def load_config(db, profile_id, settings):
    row = db.get(SearchConfiguration, profile_id)
    return {
        "version": row.version if row else 0,
        "config": row.config if row else defaults(settings),
    }


def save_config(db, profile_id, settings, version, config):
    if type(version) is not int or version < 0:
        raise ConfigurationError("invalid_version")
    config = validate_config(config, settings)
    if version == 0:
        try:
            with db.begin_nested():
                db.add(SearchConfiguration(profile_id=profile_id, version=1, config=config))
                db.flush()
        except IntegrityError:
            raise ConfigurationConflict("configuration_changed") from None
    else:
        changed = db.execute(
            update(SearchConfiguration)
            .where(
                SearchConfiguration.profile_id == profile_id,
                SearchConfiguration.version == version,
            )
            .values(version=version + 1, config=config)
        ).rowcount
        if not changed:
            raise ConfigurationConflict("configuration_changed")
    db.add(
        AuditEvent(
            actor="owner",
            entity_id=profile_id,
            event_type="search.configuration_saved",
            payload_redacted={"version": version + 1},
        )
    )
    return {"version": version + 1, "config": config}


def accepts(job, config):
    title = job["title"]
    if not any(contains(title, term) for term in config["title_terms"]):
        return False
    if any(contains(title, term) for term in config["excluded_titles"]):
        return False
    market = market_for(job)
    if market not in config["markets"]:
        return False
    text = title if config["keyword_scope"] == "title" else title + " " + job["description"]
    if any(contains(text, term) for term in config["excluded_keywords"]):
        return False
    terms = config["keywords"]
    if terms and not (all if config["keyword_mode"] == "all" else any)(
        contains(text, term) for term in terms
    ):
        return False
    market_terms = config.get(f"{market}_keywords", [])
    if market_terms and not any(contains(text, term) for term in market_terms):
        return False
    if config["locations"] and not any(
        contains(job.get("source_location", ""), term) for term in config["locations"]
    ):
        return False
    return not config["eligible_only"] or eligibility(job)["status"] == "eligible"


def select_records(payload, config, fetched_at, source_id="remotive"):
    from job_hunter.infrastructure.remotive import normalize_jobs

    if not config["enabled"] or source_id not in config["sources"]:
        return []
    records = (
        [{**job, "observed_at": fetched_at} for job in payload["jobs"]]
        if payload.get("normalized") is True
        else normalize_jobs(
            payload, ",".join(config["title_terms"]), fetched_at, exclude_junior=False
        )
    )
    return [
        {**job, "market": market_for(job)}
        for job in records
        if is_recent(job.get("published_at")) and accepts(job, config)
    ]
