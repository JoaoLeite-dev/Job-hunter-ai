"""Read projections for the local monitoring UI, with explicit synthetic-data provenance."""

from datetime import UTC
from pathlib import Path

from flask import Blueprint, current_app, jsonify
from sqlalchemy import func, select

from job_hunter.application.demo import DEMO_PROFILE_ID
from job_hunter.application.matching import eligibility
from job_hunter.infrastructure.db import (
    Application,
    AuditEvent,
    Job,
    Match,
    Profile,
    ResumeTemplate,
    ResumeVariant,
    VerifiedFact,
    utcnow,
)

blueprint = Blueprint("dashboard", __name__)


def iso(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat() if value.tzinfo is None else value.isoformat()


EVENT_LABELS = {
    "resume.imported": "Currículo mestre importado",
    "resume.fields_authorized": "Campos de edição autorizados",
    "resume.facts_confirmed": "Fatos do currículo confirmados",
    "resume.wording_confirmed": "Redação de currículo confirmada",
    "resume.variant_drafted": "Variante do currículo preparada",
    "resume.validated": "Validação de currículo concluída",
    "discovery.completed": "Busca de demonstração concluída",
    "source.completed": "Fonte de vagas processada",
    "source_failed": "Falha em uma fonte de vagas",
    "job.discovered": "Oportunidade registrada",
    "sheets.processed": "Registro sincronizado com a planilha",
    "sheets.failed": "Sincronização requer atenção",
    "profile.created": "Perfil criado",
}


def event_view(event):
    data = event.payload_redacted
    detail = ""
    if event.event_type == "discovery.completed":
        detail = f"{data.get('created', 0)} novas; {data.get('duplicates', 0)} já existentes"
    elif event.event_type == "resume.fields_authorized":
        detail = f"{len(data.get('field_ids', []))} campos autorizados"
    elif event.event_type == "resume.facts_confirmed":
        detail = "Confirmação explícita do proprietário"
    elif event.event_type == "resume.validated":
        detail = (
            "Verificações aprovadas"
            if data.get("state") == "validated"
            else "Verifique o relatório"
        )
    return {
        "id": event.id,
        "label": EVENT_LABELS.get(event.event_type, "Atualização registrada"),
        "detail": detail,
        "created_at": iso(event.created_at),
        "type": event.event_type,
    }


@blueprint.get("/api/v1/dashboard")
def dashboard():
    settings = current_app.extensions["settings"]
    with current_app.extensions["session_factory"]() as db:
        jobs = list(db.scalars(select(Job).order_by(Job.discovered_at.desc(), Job.id).limit(200)))
        templates = list(db.scalars(select(ResumeTemplate).order_by(ResumeTemplate.id)))
        profile_ids = {t.profile_id for t in templates} | {DEMO_PROFILE_ID}
        profiles = {p.id: p for p in db.scalars(select(Profile).where(Profile.id.in_(profile_ids)))}
        primary = next((t.profile_id for t in templates if t.profile_id != DEMO_PROFILE_ID), None)
        matches = {
            (m.job_id, m.profile_id): m
            for m in db.scalars(select(Match).where(Match.job_id.in_([j.id for j in jobs])))
        }
        counts = dict(
            db.execute(
                select(VerifiedFact.profile_id, func.count())
                .where(
                    VerifiedFact.verified_at.is_not(None), VerifiedFact.profile_id.in_(profile_ids)
                )
                .group_by(VerifiedFact.profile_id)
            ).all()
        )
        items = []
        for job in jobs:
            demo = job.source_id == "fixture"
            match = matches.get((job.id, DEMO_PROFILE_ID if demo else primary))
            gate = eligibility({**job.data, "status": job.status})
            items.append(
                {
                    "id": job.id,
                    "company": job.company,
                    "title": job.title,
                    "description": job.description,
                    "url": job.canonical_url,
                    "countries": job.data.get("allowed_countries", []),
                    "remote": job.data.get("remote"),
                    "status": job.status,
                    "discovered_at": iso(job.discovered_at),
                    "verified_at": iso(job.last_verified_at),
                    "is_demo": demo,
                    "eligibility": gate,
                    "score": match.score if match else None,
                    "match": match.evidence if match else None,
                    "match_profile": "Perfil sintético de demonstração"
                    if demo
                    else "Perfil principal",
                }
            )
        items.sort(
            key=lambda row: (
                {"eligible": 0, "blocked": 1, "needs_review": 2}.get(
                    row["eligibility"]["status"], 3
                ),
                row["company"].casefold(),
            )
        )
        template_items = []
        for template in templates:
            approval = template.manifest_json.get("approval") or {}
            allowed = set(approval.get("field_ids", []))
            template_items.append(
                {
                    "id": template.id,
                    "version": template.version,
                    "profile_name": profiles[template.profile_id].name,
                    "facts_count": counts.get(template.profile_id, 0),
                    "authorized_count": len(allowed),
                    "fields": [
                        {"id": f["field_id"], "section": f["section"], "text": f["original_text"]}
                        for f in template.manifest_json["fields"]
                        if f["field_id"] in allowed
                    ],
                    "is_demo": template.profile_id == DEMO_PROFILE_ID,
                    "protected": True,
                }
            )
        variants = list(db.scalars(select(ResumeVariant).order_by(ResumeVariant.id).limit(100)))
        applications = list(db.scalars(select(Application).order_by(Application.id).limit(100)))
        events = list(
            db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(40))
        )
        eligible_count = sum(
            eligibility({**data, "status": state})["status"] == "eligible"
            for data, state in db.execute(
                select(Job.data, Job.status).execution_options(yield_per=200)
            )
        )
        return jsonify(
            {
                "updated_at": iso(utcnow()),
                "stats": {
                    "jobs": db.scalar(select(func.count()).select_from(Job)),
                    "eligible": eligible_count,
                    "applications": db.scalar(select(func.count()).select_from(Application)),
                    "templates": len(templates),
                },
                "jobs": items,
                "templates": template_items,
                "variants": [
                    {
                        "id": v.id,
                        "job_id": v.job_id,
                        "template_id": v.template_id,
                        "state": v.state,
                        "validation": v.validation_json,
                        "pdf_available": bool(v.pdf_key),
                    }
                    for v in variants
                ],
                "applications": [
                    {"id": a.id, "job_id": a.job_id, "status": a.status, "recipient": a.recipient}
                    for a in applications
                ],
                "activity": [event_view(e) for e in events],
                "integrations": {
                    "discovery_mode": settings.discovery_mode,
                    "sheets_enabled": settings.sheets_sync_enabled,
                    "render_enabled": settings.resume_render_enabled
                    and (
                        Path(settings.libreoffice_binary).is_file()
                        or bool(current_app.extensions.get("baseline_preview_only"))
                    ),
                    "email_enabled": False,
                    "ai_enabled": False,
                    "preview_mode": bool(current_app.extensions.get("preview_mode", False)),
                    "baseline_preview_only": bool(
                        current_app.extensions.get("baseline_preview_only", False)
                    ),
                    "snapshot_at": current_app.extensions.get("preview_snapshot_at"),
                },
            }
        )
