from sqlalchemy.orm import Session

from job_hunter.application.discovery import Discovery
from job_hunter.application.fixtures import fixture_source
from job_hunter.infrastructure.db import Profile, VerifiedFact, utcnow

DEMO_PROFILE_ID = "00000000-0000-0000-0000-000000000001"


def seed_demo(session: Session) -> str:
    if not session.get(Profile, DEMO_PROFILE_ID):
        session.add(Profile(id=DEMO_PROFILE_ID, name="Synthetic demo; not the user profile"))
        session.flush()
        session.add(
            VerifiedFact(
                profile_id=DEMO_PROFILE_ID,
                category="technical",
                claim="React",
                evidence_source="synthetic-demo-only",
                verified_at=utcnow(),
            )
        )
    return DEMO_PROFILE_ID


def run_demo(session: Session) -> dict:
    profile_id = seed_demo(session)
    return Discovery(session).run(profile_id, {"fixture": fixture_source})
