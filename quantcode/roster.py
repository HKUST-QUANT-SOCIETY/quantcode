"""Import a survey workbook into a reviewable, non-active SSH roster candidate."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import tempfile

import yaml

from quantcode.identity import fingerprint_of_public_key

from schemas.groups import GROUP_IDS

GROUP_ALIASES = {**{group: group for group in GROUP_IDS},
    "因子组": "factor", "因子挖掘组": "factor", "基本面": "fundamental",
    "基本面组": "fundamental", "模型组": "model", "风控组": "risk",
    "基建组": "infra", "基础建设组": "infra", "infra组": "infra",
    "ai agent": "agent", "ai agent组": "agent", "agent组": "agent", "agent开发": "agent",
    "rl工程落地组": "factor", "模型 agent": "model",
    "项目风控组": "risk", "期权组": "options", "cta": "strategy", "cta组": "strategy",
}


def normalize_public_key(value: str) -> tuple[str, str]:
    """Validate using OpenSSH; recover a bare blob's embedded algorithm."""
    value = value.strip()
    if value.startswith("SHA256:"):
        raise ValueError("fingerprint_only: public key required")
    if not value or "PRIVATE KEY" in value:
        raise ValueError("missing_or_private_key")
    parts = value.split()
    try:
        blob = base64.b64decode(parts[1] if parts[0].startswith(("ssh-", "ecdsa-", "sk-")) else parts[0], validate=True)
        size = struct.unpack(">I", blob[:4])[0]
        algorithm = blob[4:4 + size].decode("ascii")
        if not algorithm.startswith(("ssh-", "ecdsa-", "sk-")) or size > 128:
            raise ValueError("invalid algorithm")
        if parts[0].startswith(("ssh-", "ecdsa-", "sk-")) and parts[0] != algorithm:
            raise ValueError("algorithm mismatch")
        key = algorithm + " " + base64.b64encode(blob).decode("ascii")
        with tempfile.TemporaryDirectory(prefix="quantcode-roster-key-") as directory:
            path = Path(directory) / "key.pub"
            path.write_text(key + "\n", encoding="utf-8")
            subprocess.run(["ssh-keygen", "-lf", str(path)], check=True, capture_output=True, timeout=5)
        return key, fingerprint_of_public_key(key)
    except (ValueError, IndexError, struct.error, UnicodeError, subprocess.SubprocessError) as exc:
        raise ValueError("invalid_public_key") from exc


def compile_records(records: list[dict], workspace_root: str) -> dict:
    """Never resolve identity conflicts or organization roles by row order."""
    if not workspace_root.startswith("/") or ".." in Path(workspace_root).parts:
        raise ValueError("workspace_root must be an absolute server path without traversal")
    people: dict[str, list[dict]] = {}
    rejected = []
    for record in records:
        email = str(record.get("email") or "").strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            rejected.append({"row": record["row"], "issues": ["invalid_email"]})
            continue
        people.setdefault(email, []).append(record)
    candidates = []
    reviews = []
    key_owners: dict[str, set[str]] = {}
    for email, entries in people.items():
        groups = {GROUP_ALIASES.get(str(row.get("group") or "").strip().lower()) for row in entries}
        suggested_groups = set()
        unknown_labels = set()
        for row in entries:
            label = str(row.get("group") or "").strip().lower()
            labels = [label] if label in GROUP_ALIASES else re.split(r"[/、，,;；]|\s+(?=风控组)", label)
            for label in labels:
                mapped = GROUP_ALIASES.get(label.strip())
                if mapped:
                    suggested_groups.add(mapped)
                elif label.strip():
                    unknown_labels.add(label.strip())
        issues = []
        if None in groups or len(groups) != 1:
            issues.append("group_confirmation_required")
        names = {str(row.get("name") or "").strip() for row in entries}
        if len(names) != 1 or not all(names):
            issues.append("name_conflict")
        keys = {}
        for row in entries:
            try:
                key, fingerprint = normalize_public_key(str(row.get("public_key") or ""))
                keys[fingerprint] = key
                key_owners.setdefault(fingerprint, set()).add(email)
            except ValueError as exc:
                issues.append(f"row_{row['row']}:{exc}")
        actor = "member-" + hashlib.sha256(email.encode()).hexdigest()[:20]
        review = {"actor_id": actor, "name": sorted(names), "email": email,
                  "rows": [row["row"] for row in entries],
                  "submitted_groups": sorted({str(row.get("group") or "") for row in entries}),
                  "issues": sorted(set(issues)), "key_count": len(keys),
                  "suggested_groups": sorted(suggested_groups), "unknown_group_labels": sorted(unknown_labels)}
        reviews.append(review)
        if issues:
            continue
        group = next(iter(groups))
        for fingerprint, key in keys.items():
            candidates.append({"fingerprint": fingerprint, "public_key": key, "actor_id": actor,
                               "group": group, "role": "analyst", "workspace_id": actor,
                               "workspace_path": str(PurePosixPath(workspace_root) / actor),
                               "resource_scopes": [f"memory:{group}"], "source_rows": review["rows"]})
    conflicted = {key for key, owners in key_owners.items() if len(owners) > 1}
    conflicted_actors = {"member-" + hashlib.sha256(email.encode()).hexdigest()[:20]
                         for key in conflicted for email in key_owners[key]}
    for review in reviews:
        if review["actor_id"] in conflicted_actors:
            review["issues"].append("public_key_shared_by_different_people")
    candidates = [row for row in candidates if row["actor_id"] not in conflicted_actors]
    return {"status": "REVIEW_REQUIRED", "bindings": candidates, "people": reviews,
            "rejected_rows": rejected, "summary": {"submissions": len(records), "people": len(people),
            "candidate_bindings": len(candidates), "pending_people": sum(bool(row["issues"]) for row in reviews),
            "rejected_rows": len(rejected)}}


def read_workbook(path: Path) -> list[dict]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = iter(sheet.values)
        header = next(rows)
        fields = {"name": "1、姓名", "group": "2、所在小组", "email": "3、GitHub邮箱", "public_key": "4、公钥"}
        if any(label not in header for label in fields.values()):
            raise ValueError("workbook is missing required roster columns")
        return [{"row": index, **{key: row[header.index(label)] for key, label in fields.items()}}
                for index, row in enumerate(rows, 2) if any(value is not None for value in row)]
    finally:
        workbook.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New local review directory; never the active roster")
    parser.add_argument("--workspace-root", required=True, help="Proposed server research workspace root; not provisioned")
    args = parser.parse_args(argv)
    result = compile_records(read_workbook(args.workbook), args.workspace_root)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name, content in {
        "candidate.yaml": yaml.safe_dump({"status": "REVIEW_REQUIRED", "bindings": result["bindings"]}, allow_unicode=True, sort_keys=False),
        "review.json": json.dumps({key: value for key, value in result.items() if key != "bindings"}, ensure_ascii=False, indent=2),
    }.items():
        path = args.output / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content + "\n")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
