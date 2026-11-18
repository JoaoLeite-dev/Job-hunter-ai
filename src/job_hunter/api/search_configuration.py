from collections import Counter

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
                sources=CATALOG,
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
            cache = db.get(SourceCache, "remotive")
            if not cache or not cache.payload or not cache.fetched_at:
                return jsonify(error="source_cache_missing"), 409
            observed = aware(cache.fetched_at).isoformat()
            records = select_records(cache.payload, config, observed)
            return jsonify(
                scanned=len(cache.payload["jobs"]),
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
