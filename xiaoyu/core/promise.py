from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from xiaoyu.contracts.common import StringEnum, datetime_from_text
from xiaoyu.persistence import Database
from xiaoyu.persistence.repositories.events import CanonicalEventRepository
from xiaoyu.persistence.repositories.promise import PromiseRepository


class PromiseState(StringEnum):
    OPEN = "OPEN"
    WAITING = "WAITING"
    FULFILLED = "FULFILLED"
    BROKEN = "BROKEN"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class PromiseAdmissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromiseView:
    promise_id: str
    identity_id: str
    state: PromiseState
    commitment_text: str
    linked_purpose_id: Optional[str]
    revision: int
    source_event_id: str


class PromiseLedger:
    """Explicit XiaoYu commitments. Promise state never authorizes an effect."""

    ALLOWED = {
        PromiseState.OPEN: {
            PromiseState.WAITING,
            PromiseState.FULFILLED,
            PromiseState.BROKEN,
            PromiseState.CANCELLED,
            PromiseState.SUPERSEDED,
        },
        PromiseState.WAITING: {
            PromiseState.OPEN,
            PromiseState.FULFILLED,
            PromiseState.BROKEN,
            PromiseState.CANCELLED,
            PromiseState.SUPERSEDED,
        },
        PromiseState.FULFILLED: set(),
        PromiseState.BROKEN: set(),
        PromiseState.CANCELLED: set(),
        PromiseState.SUPERSEDED: set(),
    }

    def __init__(
        self,
        db: Database,
        repository=None,
        event_repository=None,
    ) -> None:
        self.db = db
        self.repository = repository or PromiseRepository()
        self.event_repository = (
            event_repository or CanonicalEventRepository()
        )

    def propose_candidate(
        self,
        *,
        candidate_id: str,
        source_event_id: str,
        speaker_actor: str,
        commitment_text: str,
        explicit_commitment: bool,
        due_window: Optional[dict] = None,
        created_at: Optional[datetime] = None,
    ) -> str:
        if not commitment_text.strip():
            raise ValueError("commitment_text is required")
        at = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            event = self.event_repository.get(conn, source_event_id)
            if event is None:
                raise KeyError("unknown source event %s" % source_event_id)
            ingest_revision = self.event_repository.get_ingest_revision(
                conn, source_event_id
            )
            self.repository.insert_candidate(
                conn,
                candidate_id=candidate_id,
                identity_id=event.identity_id,
                source_event_id=source_event_id,
                source_ingest_revision=ingest_revision,
                speaker_actor=speaker_actor,
                commitment_text=commitment_text.strip(),
                due_window=due_window,
                explicit_commitment=explicit_commitment,
                created_at=at,
            )
        return candidate_id

    def promote(
        self,
        *,
        candidate_id: str,
        promise_id: str,
        transition_id: str,
        created_at: Optional[datetime] = None,
    ) -> PromiseView:
        at = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            candidate = self.repository.get_candidate(conn, candidate_id)
            if candidate is None:
                raise KeyError("unknown promise candidate %s" % candidate_id)
            if candidate["state"] != "CANDIDATE":
                raise PromiseAdmissionError("promise candidate already decided")
            if not bool(candidate["explicit_commitment"]):
                raise PromiseAdmissionError(
                    "implicit/model-like language cannot enter promise ledger"
                )
            if not str(candidate["speaker_actor"]).startswith("xiaoyu:"):
                raise PromiseAdmissionError(
                    "only trusted XiaoYu actors can own promises"
                )
            self.repository.insert_promise(
                conn,
                promise_id=promise_id,
                candidate=candidate,
                created_at=at,
            )
            self.repository.append_transition(
                conn,
                transition_id=transition_id,
                promise_id=promise_id,
                identity_id=str(candidate["identity_id"]),
                operation="CREATE",
                from_state=None,
                to_state=PromiseState.OPEN.value,
                linked_purpose_id=None,
                source_event_id=str(candidate["source_event_id"]),
                source_ingest_revision=int(
                    candidate["source_ingest_revision"]
                ),
                created_at=at,
            )
            self.repository.promote_candidate(
                conn,
                candidate_id=candidate_id,
                promise_id=promise_id,
                updated_at=at,
            )
            self.repository.overwrite_rebuilt(
                conn,
                promise_id=promise_id,
                state=PromiseState.OPEN.value,
                linked_purpose_id=None,
                revision=1,
                last_transition_id=transition_id,
                updated_at=at,
            )
            return self._view(
                self.repository.get_promise(conn, promise_id)
            )

    def transition(
        self,
        *,
        promise_id: str,
        transition_id: str,
        expected_state: PromiseState,
        to_state: PromiseState,
        source_event_id: str,
        created_at: Optional[datetime] = None,
    ) -> PromiseView:
        at = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            promise = self.repository.get_promise(conn, promise_id)
            if promise is None:
                raise KeyError("unknown promise %s" % promise_id)
            current = PromiseState(str(promise["state"]))
            if current != expected_state:
                raise PromiseAdmissionError(
                    "expected promise state %s, current is %s"
                    % (expected_state.value, current.value)
                )
            if to_state not in self.ALLOWED[current]:
                raise PromiseAdmissionError(
                    "invalid promise transition %s -> %s"
                    % (current.value, to_state.value)
                )
            event = self.event_repository.get(conn, source_event_id)
            if event is None:
                raise KeyError("unknown source event %s" % source_event_id)
            if event.identity_id != promise["identity_id"]:
                raise PromiseAdmissionError(
                    "promise transition evidence belongs to another identity"
                )
            ingest_revision = self.event_repository.get_ingest_revision(
                conn, source_event_id
            )
            self.repository.append_transition(
                conn,
                transition_id=transition_id,
                promise_id=promise_id,
                identity_id=str(promise["identity_id"]),
                operation="STATE",
                from_state=current.value,
                to_state=to_state.value,
                linked_purpose_id=promise["linked_purpose_id"],
                source_event_id=source_event_id,
                source_ingest_revision=ingest_revision,
                created_at=at,
            )
            self.repository.update_state(
                conn,
                promise_id=promise_id,
                expected_state=current.value,
                to_state=to_state.value,
                transition_id=transition_id,
                updated_at=at,
            )
            return self._view(
                self.repository.get_promise(conn, promise_id)
            )

    def link_purpose(
        self,
        *,
        promise_id: str,
        purpose_id: str,
        transition_id: str,
        source_event_id: str,
        created_at: Optional[datetime] = None,
    ) -> PromiseView:
        at = created_at or datetime.now(timezone.utc)
        with self.db.transaction(immediate=True) as conn:
            promise = self.repository.get_promise(conn, promise_id)
            if promise is None:
                raise KeyError("unknown promise %s" % promise_id)
            if PromiseState(str(promise["state"])) not in {
                PromiseState.OPEN,
                PromiseState.WAITING,
            }:
                raise PromiseAdmissionError(
                    "terminal promise cannot link a Purpose"
                )
            purpose = conn.execute(
                "SELECT identity_id FROM purposes WHERE purpose_id=?",
                (purpose_id,),
            ).fetchone()
            if purpose is None:
                raise KeyError("unknown purpose %s" % purpose_id)
            if str(purpose["identity_id"]) != str(promise["identity_id"]):
                raise PromiseAdmissionError(
                    "promise and Purpose identity mismatch"
                )
            event = self.event_repository.get(conn, source_event_id)
            if event is None:
                raise KeyError("unknown source event %s" % source_event_id)
            if event.identity_id != promise["identity_id"]:
                raise PromiseAdmissionError(
                    "link evidence belongs to another identity"
                )
            ingest_revision = self.event_repository.get_ingest_revision(
                conn, source_event_id
            )
            self.repository.append_transition(
                conn,
                transition_id=transition_id,
                promise_id=promise_id,
                identity_id=str(promise["identity_id"]),
                operation="LINK_PURPOSE",
                from_state=str(promise["state"]),
                to_state=str(promise["state"]),
                linked_purpose_id=purpose_id,
                source_event_id=source_event_id,
                source_ingest_revision=ingest_revision,
                created_at=at,
            )
            self.repository.update_link(
                conn,
                promise_id=promise_id,
                linked_purpose_id=purpose_id,
                transition_id=transition_id,
                updated_at=at,
            )
            return self._view(
                self.repository.get_promise(conn, promise_id)
            )

    def get(self, *, promise_id: str) -> PromiseView:
        with self.db.transaction() as conn:
            promise = self.repository.get_promise(conn, promise_id)
        if promise is None:
            raise KeyError("unknown promise %s" % promise_id)
        return self._view(promise)

    def rebuild(self, *, promise_id: str) -> PromiseView:
        with self.db.transaction(immediate=True) as conn:
            promise = self.repository.get_promise(conn, promise_id)
            if promise is None:
                raise KeyError("unknown promise %s" % promise_id)
            transitions = self.repository.list_transitions(
                conn, promise_id=promise_id
            )
            state: Optional[PromiseState] = None
            linked_purpose_id: Optional[str] = None
            revision = 0
            last_transition_id = ""
            last_at = None
            for row in transitions:
                operation = str(row["operation"])
                if operation == "CREATE":
                    if state is not None or row["from_state"] is not None:
                        raise PromiseAdmissionError(
                            "promise CREATE transition is malformed"
                        )
                    state = PromiseState(str(row["to_state"]))
                elif operation == "STATE":
                    if state is None:
                        raise PromiseAdmissionError(
                            "promise state transition before CREATE"
                        )
                    from_state = PromiseState(str(row["from_state"]))
                    to_state = PromiseState(str(row["to_state"]))
                    if state != from_state or to_state not in self.ALLOWED[state]:
                        raise PromiseAdmissionError(
                            "promise transition log is not replayable"
                        )
                    state = to_state
                elif operation == "LINK_PURPOSE":
                    if state is None:
                        raise PromiseAdmissionError(
                            "purpose link before promise CREATE"
                        )
                    if (
                        str(row["from_state"]) != state.value
                        or str(row["to_state"]) != state.value
                    ):
                        raise PromiseAdmissionError(
                            "purpose link changed promise state"
                        )
                    linked_purpose_id = row["linked_purpose_id"]
                else:
                    raise PromiseAdmissionError(
                        "unknown promise transition operation %s" % operation
                    )
                revision += 1
                last_transition_id = str(row["transition_id"])
                last_at = datetime_from_text(
                    str(row["created_at"]), "created_at"
                )

            if state is None or last_at is None:
                raise PromiseAdmissionError(
                    "promise has no CREATE transition"
                )
            self.repository.overwrite_rebuilt(
                conn,
                promise_id=promise_id,
                state=state.value,
                linked_purpose_id=linked_purpose_id,
                revision=revision,
                last_transition_id=last_transition_id,
                updated_at=last_at,
            )
            return self._view(
                self.repository.get_promise(conn, promise_id)
            )

    @staticmethod
    def _view(promise: dict) -> PromiseView:
        return PromiseView(
            promise_id=str(promise["promise_id"]),
            identity_id=str(promise["identity_id"]),
            state=PromiseState(str(promise["state"])),
            commitment_text=str(promise["commitment_text"]),
            linked_purpose_id=promise["linked_purpose_id"],
            revision=int(promise["revision"]),
            source_event_id=str(promise["source_event_id"]),
        )
