"""Verify identical task/artifact request targets under eight existing QA identities."""
from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse

import httpx

from run_serverc_native_members import GROUPS, Member, require, sanitize_evidence, signing_agent


def task_url(task):
    return f"/experimental/quantcode/organization-tasks/{quote(task['source_id'], safe='')}/{quote(task['session_id'], safe='')}"


def request(instance, target, records, role):
    response = instance.client.get(target)
    record = {"role": role, "request_target": response.request.url.raw_path.decode(),
              "http_status": response.status_code, "attempt": 1}
    records.append(record)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code != 200:
        record["response"] = sanitize_evidence(body, instance.secrets)
    return response, body


def require_task(response, body, instance, expected):
    require(response.status_code == 200, f"Own task read failed: HTTP {response.status_code}")
    task = body.get("task", {})
    require(task.get("actor_id") == instance.member["actor_id"], "Task actor does not match its owner")
    require(all(task.get(key) == expected[key] for key in ("source_id", "session_id")), "Task identity changed")
    require(task.get("status") == "completed", "Original task is no longer completed")
    return task


def require_artifact(response, body, artifact, revision):
    require(response.status_code == 200, f"Owner artifact read failed: HTTP {response.status_code}")
    require(body.get("source_revision") == revision and body.get("offset") == 0, "Artifact revision or offset changed")
    require(body.get("artifact", {}).get("id") == artifact["id"], "Artifact identity changed")
    require(body.get("encoding") == "base64" and body.get("next_offset") is None, "Expected the complete QA artifact")
    content = base64.b64decode(body["content"], validate=True)
    digest = hashlib.sha256(content).hexdigest()
    require(digest == artifact["sha256"] == body.get("chunk_sha256"), "Original artifact bytes changed")
    return body["content"]


def verify_pair(reader, owner, reader_task, owner_task, artifact, checks):
    # Organization APIs use the host's identity. No directory parameter means
    # both identities request precisely the same path and query string.
    endpoint = task_url(owner_task)
    initial = []
    response, body = request(owner, endpoint, initial, "owner_latest_task")
    current = require_task(response, body, owner, owner_task)
    revision = current["source_revision"]
    artifact_target = str(httpx.URL(endpoint + "/artifacts/" + quote(artifact["id"], safe=""),
                                    params={"source_revision": revision, "offset": 0}))
    for resource, target in (("task", endpoint), ("artifact", artifact_target)):
        check = {"reader": reader.member["group"], "owner": owner.member["group"], "resource": resource,
                 "source_id": current["source_id"], "session_id": current["session_id"],
                 "source_revision": revision, "request_target": target, "status": "failed", "requests": []}
        if resource == "artifact":
            check.update(artifact_id=artifact["id"], offset=0, artifact_sha256=artifact["sha256"])
        else:
            check["revision_discovery"] = initial
        checks.append(check)
        response, positive = request(owner, target, check["requests"], "owner_before")
        if resource == "task":
            confirmed = require_task(response, positive, owner, owner_task)
            require(confirmed["source_revision"] == revision, "Target revision changed during the pair")
            hidden = [confirmed["title"]]
        else:
            hidden = [artifact["id"], require_artifact(response, positive, artifact, revision)]
        denied, denied_body = request(reader, target, check["requests"], "reader_cross")
        require(denied.status_code in (400, 401, 403, 404), "Cross-member access was not denied")
        require(not any(value and value in denied.text for value in hidden), "Cross-member response disclosed protected content")
        require(not any(key in denied_body for key in ("task", "artifact", "content")), "Denied response contains protected fields")
        own_response, own_body = request(reader, task_url(reader_task), check["requests"], "reader_own_after")
        require_task(own_response, own_body, reader, reader_task)
        after_response, after_body = request(owner, target, check["requests"], "owner_after")
        if resource == "task":
            after = require_task(after_response, after_body, owner, owner_task)
            require(after["source_revision"] == revision, "Target revision changed after cross-member access")
        else:
            require_artifact(after_response, after_body, artifact, revision)
        matched = [record["request_target"] for record in check["requests"] if record["role"] != "reader_own_after"]
        require(matched == [target] * 3, "Owner and reader requested different resources")
        check.update(status="passed", http_status=denied.status_code, same_target_verified=True)


def close_member(instance, own_task, logout):
    record = {"group": instance.member["group"], "status": "failed"}
    logout.append(record)
    try:
        require(instance.logged_in, "Member never completed authentication")
        instance.request("POST", "/experimental/quantcode/identity/logout", {}, scoped=False)
        identity = instance.request("GET", "/experimental/quantcode/identities", scoped=False)
        require(identity.get("session") is None, "Logout did not clear the host login")
        response = instance.client.get(task_url(own_task))
        workspace = instance.client.get("/experimental/quantcode/workspaces")
        record.update(task_after_logout_http=response.status_code, workspace_after_logout_http=workspace.status_code)
        require(response.status_code in (400, 401, 403), "Logout did not revoke the previously readable task")
        require(workspace.status_code in (400, 401, 403), "Logout did not revoke workspace access")
        instance.logged_in = False
        record["status"] = "passed"
    except Exception as error:
        record["error"] = sanitize_evidence(str(error), instance.secrets)
    finally:
        instance.client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--lifecycle-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Refusing to overwrite an existing evidence report")
    manifest = json.loads(args.manifest.read_text())
    lifecycle = json.loads(args.lifecycle_report.read_text())
    require(manifest.get("purpose") == "isolated-eight-group-e2e", "Only isolated QA deployments are accepted")
    by_group = {item["group"]: item for item in manifest["members"]}
    completed = {item["group"]: item for item in lifecycle["members"]
                 if item.get("status") == "passed" and item.get("task") and item.get("artifact")}
    require(set(completed) == set(GROUPS) == set(by_group), "Exactly eight completed QA member records are required")
    members = [by_group[group] for group in GROUPS]
    for member in members:
        require(member["actor_id"].startswith("sim-") and member["username"].startswith("qc-sim-"), "Non-QA member")
        require(PurePosixPath(member["workspace"]).is_relative_to("/srv/quantcode-qa"), "Non-QA workspace")
        require(urlparse(member["native_base_url"]).hostname == "127.0.0.1", "Host must use a local SSH tunnel")
    require(len({member["fingerprint"] for member in members}) == 8, "Member keys are not independent")
    require(len({member["native_base_url"] for member in members}) == 8, "Member hosts are not independent")
    report = {"mode": "verify-existing-native-cross-boundaries", "started_at": datetime.now(timezone.utc).isoformat(),
              "source_report": str(args.lifecycle_report), "source_report_sha256": hashlib.sha256(args.lifecycle_report.read_bytes()).hexdigest(),
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "model_requests": 0,
              "status": "failed", "members": [], "cross_member_checks": [], "logout": [],
              "expected_cross_member_checks": 112, "retry_policy": "none; every request is recorded"}
    try:
        with signing_agent(members) as agent_env, ExitStack() as stack:
            clients = {}
            for member in members:
                instance = Member(member, "verify-existing", {}, agent_env, 60)
                settings = dict(line.split("=", 1) for line in Path(member["native_password_file"]).read_text().splitlines() if "=" in line)
                password = settings["OPENCODE_SERVER_PASSWORD"]
                instance.secrets.append(password)
                instance.client = httpx.Client(base_url=member["native_base_url"],
                    auth=(member["native_username"], password), timeout=45, trust_env=False)
                stack.callback(close_member, instance, completed[member["group"]]["task"], report["logout"])
                instance.login()
                clients[member["group"]] = instance
                report["members"].append({"group": member["group"], "login": "passed"})
            for reader_group in GROUPS:
                for owner_group in GROUPS:
                    if owner_group == reader_group:
                        continue
                    verify_pair(clients[reader_group], clients[owner_group], completed[reader_group]["task"],
                                completed[owner_group]["task"], completed[owner_group]["artifact"], report["cross_member_checks"])
                    print(json.dumps({"reader": reader_group, "owner": owner_group, "checks": len(report["cross_member_checks"])}), flush=True)
        require(len(report["cross_member_checks"]) == 112, "Incomplete cross-member matrix")
        require(all(item["status"] == "passed" for item in report["cross_member_checks"]), "Cross-member verification failed")
        require(len(report["logout"]) == 8 and all(item["status"] == "passed" for item in report["logout"]), "Logout verification failed")
        report["status"] = "passed"
    except Exception as error:
        report["error"] = sanitize_evidence(str(error))
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(sanitize_evidence(report), output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"output": str(args.output), "status": report["status"], "cross_member_checks": len(report["cross_member_checks"]),
                      "verified_logouts": sum(item["status"] == "passed" for item in report["logout"])}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
