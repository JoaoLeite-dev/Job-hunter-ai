from enum import StrEnum


class Status(StrEnum):
    DISCOVERED = "discovered"
    ELIGIBLE = "eligible"
    RANKED = "ranked"
    CV_DRAFTING = "cv_drafting"
    VALIDATION_FAILED = "validation_failed"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    QUEUED = "queued"
    SENT = "sent"
    SEND_FAILED = "send_failed"
    CONTACT_MISSING = "contact_missing"
    REJECTED = "rejected"
    INTERVIEW = "interview"
    CLOSED = "closed"


TRANSITIONS: dict[Status, set[Status]] = {
    Status.DISCOVERED: {Status.ELIGIBLE},
    Status.ELIGIBLE: {Status.RANKED},
    Status.RANKED: {Status.CV_DRAFTING, Status.CONTACT_MISSING},
    Status.CONTACT_MISSING: {Status.CV_DRAFTING},
    Status.CV_DRAFTING: {Status.READY_FOR_REVIEW, Status.VALIDATION_FAILED},
    Status.VALIDATION_FAILED: {Status.CV_DRAFTING},
    Status.READY_FOR_REVIEW: {Status.APPROVED, Status.REJECTED},
    Status.APPROVED: {Status.QUEUED, Status.READY_FOR_REVIEW, Status.REJECTED},
    Status.QUEUED: {Status.SENT, Status.SEND_FAILED},
    Status.SEND_FAILED: {Status.READY_FOR_REVIEW},
    Status.SENT: {Status.INTERVIEW, Status.CLOSED},
    Status.INTERVIEW: {Status.CLOSED},
}


def transition(current: Status, target: Status, *, authorized: bool = False) -> Status:
    if target not in TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid transition: {current} -> {target}")
    if target in {Status.APPROVED, Status.QUEUED, Status.SENT} and not authorized:
        raise ValueError("Transition requires validated approval or provider confirmation")
    return target
