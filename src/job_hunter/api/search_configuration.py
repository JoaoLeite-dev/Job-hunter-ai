from collections import Counter
from urllib.parse import quote, urlencode

from flask import Blueprint, current_app, jsonify, request

from job_hunter.application.live_discovery import aware, profile_id_for
from job_hunter.application.search_configuration import (
    CATALOG,
    ConfigurationConflict,
    ConfigurationError,
    load_config,
    save_config,
    select_records,
    validate_config,
)
from job_hunter.infrastructure.db import SourceCache
from job_hunter.infrastructure.remotive import SourceError

blueprint = Blueprint("search_configuration", __name__)


def source_catalog(db, config):
    term = " OR ".join(config["title_terms"][:3])
    result = []
    for item in CATALOG:
        row = {**item}
        if item["id"] == "linkedin":
            row["search_url"] = (
                item["url"]
                + "?"
                + urlencode(
                    {"keywords": term, "datePosted": '"past-month"', "sortBy": '"date_posted"'}
                )
            )
        elif item["id"] == "indeed":
            row["search_url"] = (
                item["url"] + "?" + urlencode({"q": term, "l": "Brasil", "fromage": 30})
            )
        elif item["id"] == "catho":
            row["search_url"] = item["url"] + quote(config["title_terms"][0], safe="") + "/"
        else:
            row["search_url"] = item["url"]
        cache = db.get(SourceCache, item["id"])
        row["last_fetched_at"] = (
            aware(cache.fetched_at).isoformat() if cache and cache.fetched_at else None
        )
        row["error_code"] = cache.error_code if cache else None
        row["queries"] = (cache.payload or {}).get("queries", []) if cache else []
        result.append(row)
    return result


@blueprint.route("/api/v1/search-settings", methods=["GET", "PUT"])
def search_settings():
    settings = current_app.extensions["settings"]
    try:
        with current_app.extensions["session_factory"].begin() as db:
            profile_id = profile_id_for(db, settings.discovery_profile_id)
            if request.method == "PUT":
                body = request.get_json(silent=True)
                if not isinstance(body, dict) or set(body) != {"version", "config"}:
                    raise ConfigurationError("invalid_configuration_fields")
                result = save_config(db, profile_id, settings, body["version"], body["config"])
            else:
                result = load_config(db, profile_id, settings)
            return jsonify(
                **result,
                sources=source_catalog(db, result["config"]),
                publication_max_age_days=30,
                schedule={"cron": settings.cron, "timezone": settings.timezone},
                discovery_mode=settings.discovery_mode,
            )
    except ConfigurationConflict as error:
        return jsonify(error=str(error)), 409
    except ConfigurationError as error:
        return jsonify(error=str(error)), 400
    except SourceError as error:
        return jsonify(error=str(error)), 409


@blueprint.post("/api/v1/search-settings/preview")
def preview_search():
    settings = current_app.extensions["settings"]
    try:
        with current_app.extensions["session_factory"]() as db:
            profile_id_for(db, settings.discovery_profile_id)
            body = request.get_json(silent=True)
            config = validate_config(body, settings)
            caches = [db.get(SourceCache, identity) for identity in config["sources"]]
            caches = [cache for cache in caches if cache and cache.payload and cache.fetched_at]
            if not caches:
                return jsonify(error="source_cache_missing"), 409
            observed = min(aware(cache.fetched_at) for cache in caches).isoformat()
            records = [
                row
                for cache in caches
                for row in select_records(
                    cache.payload, config, aware(cache.fetched_at).isoformat(), source_id=cache.id
                )
            ]
            return jsonify(
                scanned=sum(len(cache.payload["jobs"]) for cache in caches),
                missing_sources=[
                    identity
                    for identity in config["sources"]
                    if identity not in {cache.id for cache in caches}
                ],
                matched=len(records),
                markets=dict(Counter(j["market"] for j in records)),
                fetched_at=observed,
                samples=[
                    {"title": j["title"], "company": j["company"], "market": j["market"]}
                    for j in records[:5]
                ],
            )
    except ConfigurationError as error:
        return jsonify(error=str(error)), 400
    except SourceError as error:
        return jsonify(error=str(error)), 409
