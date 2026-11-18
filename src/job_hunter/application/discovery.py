"""Transactional discovery. Connectors provide structured records, not executable instructions."""

from collections.abc import Callable, Iterable
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_hunter.application.matching import Fact, canonicalize, score
from job_hunter.application.publication import publication_time
from job_hunter.infrastructure.db import AuditEvent, Job, Match, Outbox, Profile, VerifiedFact


class Discovery:
    def __init__(self, session: Session):
        self.session = session

    def run(self, profile_id: str, sources: dict[str, Callable[[], Iterable[dict]]]) -> dict:
        if not self.session.get(Profile, profile_id):
            raise ValueError("Profile does not exist")
        facts = [
            Fact(f.id, f.category, f.claim, f.verified_at is not None)
            for f in self.session.scalars(
                select(VerifiedFact).where(VerifiedFact.profile_id == profile_id)
            )
        ]
        summary = {
            "created": 0,
            "updated": 0,
            "duplicates": 0,
            "failed_sources": [],
            "invalid_records": 0,
        }
        for source_id, fetch in sources.items():
            try:
                records = list(fetch())
            except Exception:
                summary["failed_sources"].append(source_id)
                self.session.add(
                    AuditEvent(
                        actor="discovery",
                        entity_id=source_id,
                        event_type="source_failed",
                        payload_redacted={},
                    )
                )
                continue
            for raw in records:
                try:
                    with self.session.begin_nested():
                        url = canonicalize(raw["url"])
                        external_id = raw.get("external_id")
                        identity = Job.canonical_url == url
                        if external_id:
                            identity = or_(
                                identity,
                                (Job.source_id == source_id)
                                & (Job.external_id == str(external_id)),
                            )
                        existing = self.session.scalar(select(Job).where(identity))
                        if existing:
                            # Refresh live evidence while preserving identity/history.
                            if (
                                source_id
                                in {"remotive", "infojobs", "vagas", "trabalhabrasil", "indeed"}
                                and existing.source_id == source_id
                            ):
                                result = score(raw, facts)
                                match = self.session.scalar(
                                    select(Match).where(
                                        Match.job_id == existing.id,
                                        Match.profile_id == profile_id,
                                    )
                                )
                                changed = (
                                    existing.data != raw
                                    or match is None
                                    or match.evidence != result
                                )
                                existing.company, existing.title = (
                                    raw["company"].strip(),
                                    raw["title"].strip(),
                                )
                                existing.description, existing.data = raw["description"], raw
                                existing.canonical_url = url
                                existing.published_at = publication_time(raw.get("published_at"))
                                existing.status = raw.get("status", "unknown")
                                existing.last_verified_at = datetime.fromisoformat(
                                    raw["observed_at"]
                                )
                                if match is None:
                                    match = Match(job_id=existing.id, profile_id=profile_id)
                                    self.session.add(match)
                                match.score, match.hard_gate, match.evidence = (
                                    result["score"],
                                    result["hard_gate"],
                                    result,
                                )
                                if changed:
                                    self.session.add(
                                        Outbox(
                                            entity_id=existing.id,
                                            event_type="job.updated",
                                            payload={"job_id": existing.id},
                                        )
                                    )
                                    self.session.add(
                                        AuditEvent(
                                            actor="discovery",
                                            entity_id=existing.id,
                                            event_type="job.updated",
                                            payload_redacted={"source_id": source_id},
                                        )
                                    )
                                    summary["updated"] += 1
                            summary["duplicates"] += 1
                            continue
                        result = score(raw, facts)
                        job = Job(
                            source_id=source_id,
                            external_id=external_id,
                            canonical_url=url,
                            company=raw["company"].strip(),
                            title=raw["title"].strip(),
                            description=raw["description"],
                            status=raw.get("status", "unknown"),
                            data=raw,
                            published_at=publication_time(raw.get("published_at")),
                            last_verified_at=datetime.fromisoformat(raw["observed_at"])
                            if raw.get("observed_at")
                            else None,
                        )
                        self.session.add(job)
                        self.session.flush()
                        self.session.add(
                            Match(
                                job_id=job.id,
                                profile_id=profile_id,
                                score=result["score"],
                                hard_gate=result["hard_gate"],
                                evidence=result,
                            )
                        )
                        self.session.add(
                            Outbox(
                                entity_id=job.id,
                                event_type="job.discovered",
                                payload={"job_id": job.id},
                            )
                        )
                        self.session.add(
                            AuditEvent(
                                actor="discovery",
                                entity_id=job.id,
                                event_type="job.discovered",
                                payload_redacted={"source_id": source_id},
                            )
                        )
                    summary["created"] += 1
                except IntegrityError:
                    summary["duplicates"] += 1
                except (KeyError, TypeError, ValueError, AttributeError):
                    summary["invalid_records"] += 1
            self.session.add(
                AuditEvent(
                    actor="discovery",
                    entity_id=source_id,
                    event_type="source.completed",
                    payload_redacted={},
                )
            )
        self.session.add(
            AuditEvent(
                actor="discovery",
                entity_id=profile_id,
                event_type="discovery.completed",
                payload_redacted=summary,
            )
        )
        return summary
