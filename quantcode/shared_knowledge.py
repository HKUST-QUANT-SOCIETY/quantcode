"""Organization-owned candidate index using existing Distill and review rules."""
from __future__ import annotations
from quantcode.knowledge_host import DistillInput, ListInput, ReviewInput, handle_scoped
from quantcode import native_tasks


def handle(gateway, token: str, action: str, request: dict) -> dict:
    if set(request) != {"expected_session_id", "payload"} or not isinstance(request["payload"], dict):
        raise ValueError("invalid organization knowledge request")
    context = gateway.session(token)
    if context.session_id != request["expected_session_id"]:
        raise PermissionError("knowledge login changed")
    schema = {"list": ListInput, "review": ReviewInput, "distill": DistillInput}.get(action)
    if schema is None:
        raise ValueError("unsupported knowledge action")
    value = schema.model_validate(request["payload"])
    snapshot = context.model_dump(mode="json")

    def revalidate():
        if gateway.session(token).model_dump(mode="json") != snapshot:
            raise PermissionError("knowledge authority changed")
        if isinstance(value, DistillInput):
            # A host may contribute only its own published native task. Admin
            # read privileges cannot be used to adopt another member's source.
            conn = native_tasks._connection(gateway)
            try:
                row = conn.execute(native_tasks.native_task_migration.records_sql() + "SELECT * FROM native_task_records WHERE source_id=? AND session_id=?",
                                   (value.source_id, value.session_id)).fetchone()
                if row is None:
                    raise PermissionError("knowledge source task is not published")
                task, owner = native_tasks._stored_task(row)
                if owner != native_tasks._owner(context) or task["root_session_id"] != value.root_session_id or task["source_revision"] < value.source_revision:
                    raise PermissionError("knowledge source ownership or revision changed")
            finally:
                conn.close()
    if isinstance(value, DistillInput) and len({item.call_id for item in value.tools}) != len(value.tools):
        raise ValueError("duplicate native tool call id")
    revalidate()
    root = gateway.database.parent / "knowledge"
    return handle_scoped(action, value, {**snapshot, "evidence_dir": root / "audit"}, root / "candidates", root / "published", revalidate)
