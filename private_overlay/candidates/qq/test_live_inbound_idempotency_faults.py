from types import SimpleNamespace

from plugin.plugins.qq_auto_reply.catchup_service import QQMessageCatchupService


def _message(mid: str, *, post_type: str = "message") -> dict:
    return {
        "post_type": post_type,
        "message_type": "private",
        "user_id": "owner",
        "message_id": mid,
        "time": 1,
        "message": [{"type": "text", "data": {"text": "fault"}}],
    }


def _service() -> QQMessageCatchupService:
    return QQMessageCatchupService(SimpleNamespace(logger=None))


def test_repeated_live_event_burst_has_exactly_one_owner() -> None:
    svc = _service()
    event = _message("stable-burst-id")

    verdicts = [svc.claim_inbound_message(dict(event)) for _ in range(256)]

    assert verdicts.count(True) == 1
    assert verdicts.count(False) == 255
    assert svc._diag["skipped_inbound_dup"] == 255


def test_live_and_catchup_paths_share_the_same_claim_authority() -> None:
    svc = _service()
    event = _message("live-catchup-overlap")

    # First claim models the live websocket path. A catch-up replay of the same
    # stable OneBot message_id must lose against that exact same authority.
    assert svc.claim_inbound_message(dict(event)) is True
    assert svc.claim_inbound_message(dict(event)) is False
    assert list(svc._recent_ids) == ["live-catchup-overlap"]


def test_non_message_events_and_missing_ids_keep_existing_passthrough() -> None:
    svc = _service()

    notice = _message("notice-id", post_type="notice")
    assert svc.claim_inbound_message(dict(notice)) is True
    assert svc.claim_inbound_message(dict(notice)) is True

    no_id = _message("")
    no_id.pop("message_id")
    assert svc.claim_inbound_message(dict(no_id)) is True
    assert svc.claim_inbound_message(dict(no_id)) is True

    assert svc._diag["skipped_inbound_dup"] == 0
