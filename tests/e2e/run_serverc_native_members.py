"""Run real native QuantCode member tasks against isolated staging hosts.

The manifest must come from the eight-group staging deployment. This script
never creates task projections or artifacts itself: the native Agent executes
the original prompt, and the host publishes its actual task/event/artifact data.
The proxy credential is a disposable QA token, never an upstream model key.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time
from urllib.parse import quote, urlparse
import uuid

import httpx


GROUPS = ("fundamental", "factor", "model", "risk", "strategy", "options", "infra", "agent")
PROVIDER = "qa-qwen"
MODEL = "qwen3.7-flash"


def sanitize_evidence(value, secrets=()):
    sensitive = {"authorization", "cookie", "setcookie", "headers", "requestheaders", "responseheaders",
                 "key", "apikey", "token", "accesstoken", "refreshtoken", "password", "secret", "clientsecret", "privatekey"}
    if isinstance(value, dict):
        return {key: "[REDACTED]" if re.sub(r"[-_]", "", key).lower() in sensitive else sanitize_evidence(item, secrets)
                for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_evidence(item, secrets) for item in value]
    if not isinstance(value, str):
        return value
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", "[REDACTED PRIVATE KEY]", value)
    value = re.sub(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/-]+=*", "[REDACTED AUTHORIZATION]", value, flags=re.I)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[REDACTED API KEY]", value)
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return value
    if isinstance(parsed, (dict, list)):
        cleaned = sanitize_evidence(parsed, secrets)
        if cleaned != parsed:
            return json.dumps(cleaned, ensure_ascii=False)
    return value


def transcript_evidence(messages, secrets=()):
    captured = []
    for message in messages:
        info = message.get("info", {})
        if info.get("role") != "assistant":
            continue
        item = {key: info.get(key) for key in ("id", "finish", "error", "time", "tokens", "cost")}
        item["parts"] = []
        for part in message.get("parts", []):
            if part.get("type") == "text":
                item["parts"].append({"type": "text", "text": part.get("text", "")})
            elif part.get("type") == "tool":
                state = part.get("state", {})
                item["parts"].append({"type": "tool", "tool": part.get("tool"), "call_id": part.get("callID"),
                                      **{key: state.get(key) for key in ("status", "input", "output", "error", "time")}})
        captured.append(item)
    return sanitize_evidence(captured, secrets)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def private_json(path):
    path = Path(path)
    require(path.stat().st_mode & 0o077 == 0, "QA credential file must be owner-only")
    return json.loads(path.read_text())


@contextmanager
def signing_agent(members):
    with tempfile.TemporaryDirectory(prefix="qc-live-agent-", dir="/tmp") as folder:
        socket = str(Path(folder) / "socket")
        process = subprocess.Popen(["ssh-agent", "-D", "-a", socket], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        env = {**os.environ, "SSH_AUTH_SOCK": socket}
        try:
            deadline = time.monotonic() + 5
            while not Path(socket).exists():
                require(process.poll() is None and time.monotonic() < deadline, "Isolated signing agent did not start")
                time.sleep(0.02)
            for member in members:
                result = subprocess.run(["ssh-add", member["private_key_file"]], env=env, capture_output=True, timeout=15)
                require(result.returncode == 0, "Could not load an isolated member key")
            yield env
        finally:
            process.terminate()
            process.wait(timeout=5)


class Member:
    def __init__(self, member, run_id, proxy, agent_env, timeout, continuation_mode="text", require_continuation=False):
        self.member, self.run_id, self.proxy, self.agent_env = member, run_id, proxy, agent_env
        self.timeout = timeout
        self.continuation_mode = continuation_mode
        self.require_continuation = require_continuation
        self.session_id = None
        self.created_sessions = []
        self.logged_in = False
        self.filename = f"qa-result-{run_id}.json"
        self.result = {"group": member["group"], "actor_id": member["actor_id"], "status": "pending", "steps": []}
        self.client = None
        self.secrets = [proxy.get("token", "")]
        self.approved_proposals = {}

    def request(self, method, endpoint, payload=None, query=None, *, allowed=(200,), scoped=True):
        params = {"directory": self.member["workspace"]} if scoped else {}
        params.update(query or {})
        response = self.client.request(method, endpoint, params=params, **({"json": payload} if payload is not None else {}))
        if response.status_code not in allowed:
            reference = ""
            error = response.text
            try:
                error = response.json()
                ref = error.get("data", {}).get("ref") if isinstance(error, dict) else None
                if isinstance(ref, str) and ref.startswith("err_") and ref[4:].isalnum():
                    reference = f" ({ref})"
            except (ValueError, AttributeError):
                pass
            self.result.setdefault("http_errors", []).append(sanitize_evidence({"method": method, "endpoint": endpoint,
                "http_status": response.status_code, "response": error}, self.secrets))
            raise AssertionError(f"{method} {endpoint}: HTTP {response.status_code}{reference}")
        return response.json() if response.content else None

    def step(self, name, **evidence):
        if "status" in evidence:
            evidence["task_status"] = evidence.pop("status")
        self.result["steps"].append({"name": name, "status": "passed", **evidence})
        print(json.dumps({"group": self.member["group"], "step": name, "status": "passed"}), flush=True)

    def login(self):
        identities = self.request("GET", "/experimental/quantcode/identities", scoped=False)
        require(not identities.get("error"), "Host identity inspection failed")
        selected = next((entry for entry in identities.get("identities", []) if entry.get("fingerprint") == self.member["fingerprint"]), None)
        require(selected is not None and selected["group"] == self.member["group"], "Host did not list this simulated member identity")
        if identities.get("session"):
            self.request("POST", "/experimental/quantcode/identity/logout", {}, scoped=False)
        challenge = self.request("POST", "/experimental/quantcode/identity/challenge", {"identity_id": selected["id"]}, scoped=False)
        require(challenge["fingerprint"] == self.member["fingerprint"], "Challenge changed the selected fingerprint")
        signed = subprocess.run(["ssh-keygen", "-Y", "sign", "-U", "-f", self.member["public_key_file"], "-n", "quantcode"],
                                input=challenge["nonce"], text=True, env=self.agent_env, capture_output=True, timeout=20)
        require(signed.returncode == 0, "Local SSH Agent could not sign the selected challenge")
        identity = self.request("POST", "/experimental/quantcode/identity/verify",
                                {"challenge_id": challenge["challenge_id"], "signature": signed.stdout}, scoped=False)
        require(identity.get("group") == self.member["group"] and identity.get("actor_id") == self.member["actor_id"], "Signed identity does not match the expected member")
        self.logged_in = True
        self.step("local_agent_login", group=identity["group"], fingerprint=identity["fingerprint"])

    def configure_model(self):
        require(self.proxy["model"] == MODEL, "Only the authorized Qwen model may be configured")
        url = self.proxy["base_url"]
        self.request("PUT", f"/auth/{PROVIDER}", {"type": "api", "key": self.proxy["token"],
                     "metadata": {"quantcode_base_url": url}}, scoped=False)
        connection = {"name": "QA Qwen", "npm": "@ai-sdk/openai-compatible", "options": {"baseURL": url},
                      "models": {MODEL: {"name": MODEL, "tool_call": True, "limit": {"context": 65536, "output": 4096}}}}
        self.request("PATCH", "/global/config", {"provider": {PROVIDER: connection},
                     "model": f"{PROVIDER}/{MODEL}", "small_model": f"{PROVIDER}/{MODEL}"}, scoped=False)
        configured = self.request("GET", "/global/config", scoped=False)
        require(configured.get("model") == f"{PROVIDER}/{MODEL}", "The chosen model was not saved")
        require(self.proxy["token"] not in json.dumps(configured), "Public model settings leaked a credential")
        self.step("single_model_configuration", model=MODEL, transport="real Qwen through QA memory-only proxy")

    def prompt(self, text):
        self.request("POST", f"/session/{self.session_id}/prompt_async", {"agent": "build",
                     "model": {"providerID": PROVIDER, "modelID": MODEL},
                     "parts": [{"type": "text", "text": text}] if text is not None else []}, allowed=(200, 204))

    def review_pending(self):
        prefix = f"/experimental/quantcode/session/{self.session_id}"
        reuse = self.request("GET", prefix + "/reuse")
        if reuse.get("proposal") and not reuse.get("review"):
            proposal = reuse["proposal"]
            signature = json.dumps({key: proposal.get(key) for key in
                ("intent_hash", "inspection_hash", "coverage", "components", "reason")}, sort_keys=True)
            require(signature not in self.approved_proposals,
                    "An identical coverage proposal lost its recorded approval and requested a second review")
            require(proposal["coverage"] in ("none", "partial"), "This generic QA file task must not claim canonical component coverage")
            self.request("POST", prefix + "/reuse/review", {"proposal_hash": proposal["proposal_hash"], "decision": "approve",
                         "note": f"QA member approves only reading qa-input.json and writing {self.filename} in the personal workspace."})
            self.approved_proposals[signature] = proposal["proposal_hash"]
            self.step("exact_coverage_review", proposal_hash=proposal["proposal_hash"], coverage=proposal["coverage"])
        solution = self.request("GET", prefix + "/solution")
        if solution.get("solution", {}).get("status") == "draft":
            draft = solution["solution"]
            workspace = PurePosixPath(self.member["workspace"])
            require(all(".." not in PurePosixPath(item).parts and
                        (PurePosixPath(item) if PurePosixPath(item).is_absolute() else workspace / item) == workspace / self.filename
                        for item in draft["file_impact"]), "Solution proposes files outside the authorized QA change")
            self.request("POST", prefix + "/solution/review", {"expected_hash": draft["doc_hash"],
                         "expected_version": draft["version"], "decision": "approve", "note": "Approve the exact personal QA file change only."})
            self.step("exact_solution_review", version=draft["version"])
        self.result["classification"] = solution.get("classification")
        permissions = self.request("GET", "/permission")
        for pending in permissions:
            if pending.get("sessionID") != self.session_id:
                continue
            permitted = {self.filename, self.member["workspace"] + "/" + self.filename}
            if pending["permission"] == "read":
                permitted |= {"qa-input.json", self.member["workspace"] + "/qa-input.json"}
            allowed = pending["permission"] in ("read", "edit") and bool(pending["patterns"]) and set(pending["patterns"]) <= permitted
            self.request("POST", "/permission/" + quote(pending["id"], safe="") + "/reply", {"reply": "once" if allowed else "reject"})
            require(allowed, "Task requested a tool/file permission beyond this QA input and output")
            self.step("scoped_file_permission", permission=pending["permission"], patterns=pending["patterns"])
        questions = self.request("GET", "/question")
        for pending in questions:
            if pending.get("sessionID") != self.session_id:
                continue
            answer = f"Proceed with the existing QA scope: read qa-input.json and write {self.filename}. Do not access production or other members."
            self.request("POST", "/question/" + quote(pending["id"], safe="") + "/reply",
                         {"answers": [[answer] for _ in pending["questions"]]})
            self.step("scoped_user_answer")
        return reuse

    def wait_for_task(self):
        deadline = time.monotonic() + self.timeout
        reminders = set()
        while time.monotonic() < deadline:
            messages = self.request("GET", f"/session/{self.session_id}/message")
            if not messages:
                time.sleep(1)
                continue
            reuse = self.review_pending()
            status = self.request("GET", "/session/status").get(self.session_id, {}).get("type", "idle")
            assistants = [message for message in messages if message.get("info", {}).get("role") == "assistant"]
            if status == "idle" and assistants:
                last = assistants[-1]["info"]
                if last.get("error"):
                    detail = last["error"].get("data", {}).get("message") or last["error"].get("name", "unknown error")
                    raise AssertionError("Native model execution failed: " + sanitize_evidence(detail, self.secrets))
                if last.get("finish") != "stop":
                    time.sleep(1)
                    continue
                review = self.request("GET", f"/experimental/quantcode/session/{self.session_id}/reuse")
                if review.get("review", {}).get("decision") == "approve":
                    file = self.client.get("/file/content", params={"directory": self.member["workspace"], "path": self.filename})
                    if file.status_code == 200:
                        try:
                            output = json.loads(file.json()["content"])
                        except (ValueError, KeyError, TypeError):
                            output = None
                        if output is not None:
                            return messages, output, file.json()["content"]
                marker = last.get("id")
                if marker not in reminders and len(reminders) < 3:
                    reminders.add(marker)
                    if not reuse.get("proposal"):
                        text = "Please state the actual capability gap through the task's organization_reuse proposal. This is a personal QA file task, not a canonical financial calculation."
                    else:
                        text = f"The exact task review is complete. Continue the original request, save {self.filename}, then read it back."
                    if self.continuation_mode == "empty" and review.get("review", {}).get("decision") == "approve":
                        text = None
                    self.prompt(text)
                    after = self.request("GET", f"/experimental/quantcode/session/{self.session_id}/reuse")
                    self.result.setdefault("continuations", []).append({"text": text, "before_intent_hash": review.get("intent_hash"),
                        "after_intent_hash": after.get("intent_hash"), "before_approved": review.get("review", {}).get("decision") == "approve",
                        "after_approved": after.get("review", {}).get("decision") == "approve"})
            time.sleep(1)
        raise AssertionError("Native task timed out before a verified file result")

    def run(self):
        try:
            credential = Path(self.member["native_password_file"])
            require(credential.stat().st_mode & 0o077 == 0, "Native test password file must be owner-only")
            settings = dict(line.split("=", 1) for line in credential.read_text().splitlines() if "=" in line)
            self.secrets.append(settings["OPENCODE_SERVER_PASSWORD"])
            self.client = httpx.Client(base_url=self.member["native_base_url"], auth=(self.member["native_username"], settings["OPENCODE_SERVER_PASSWORD"]),
                                       timeout=45, trust_env=False, follow_redirects=False)
            health = self.request("GET", "/global/health", scoped=False)
            require(health.get("healthy") is True, "Native host is not healthy")
            self.step("native_host_health", version=health.get("version"))
            self.login()
            self.configure_model()
            workspaces = self.request("GET", "/experimental/quantcode/workspaces", query={"preferred": self.member["workspace"]}, scoped=False)
            require(workspaces.get("preferred") == self.member["workspace"], "Roster workspace was not authorized")
            self.step("authorized_directory", roots=workspaces["roots"])
            inputs = self.request("GET", "/file/content", query={"path": "qa-input.json"})
            require(json.loads(inputs["content"])["group"] == self.member["group"], "QA input belongs to another group")
            skills = self.request("GET", "/experimental/quantcode/tool", query={"tool": "list_skills", "group": self.member["group"]})
            require(bool(skills.get("skills")), "No published group skills are available")
            self.step("published_group_skills", skill_ids=[item["id"] for item in skills["skills"]])
            cards = self.request("GET", "/experimental/quantcode/tool", query={"tool": "list_capabilities"})
            self.result["capability_statuses"] = [{"id": item["id"], "integration_status": item.get("integration_status")} for item in cards.get("capabilities", [])]
            session = self.request("POST", "/session", {"title": f"QA {self.member['group']} {self.run_id}"})
            self.session_id = session["id"]
            self.created_sessions.append(self.session_id)
            self.result["session_id"] = self.session_id
            binding = session["metadata"]["quantcode"]
            require(binding["engine"] == "quantcode" and binding["owner"]["actor_id"] == self.member["actor_id"], "Session has no native member ownership")
            require(binding["owner"]["role"] == "analyst" and binding["owner"]["group"] == self.member["group"], "The simulated member must keep its ordinary group role")
            self.step("native_session_created", session_id=self.session_id)
            prompt = (f"I am working in the {self.member['group']} group's personal research workspace. "
                      f"Read the existing {self.member['workspace']}/qa-input.json and create only {self.filename} next to it. "
                      "The JSON output must contain exactly six fields: group copied from the input, count, sum, min, max computed from its values, "
                      "and input_file set to qa-input.json. Read the new file back and check the result. "
                      "This is a small engineering acceptance task using synthetic integers, not an investment analysis. "
                      "Use the existing organization capability and group Memory checks; report any unavailable domain components honestly. "
                      "For this file-only task no canonical research component is applicable: record coverage as none with an empty component list, "
                      "and wait for my task review before writing. No component requirement is not full component coverage. "
                      "Do not change other files, fetch market data, access production, post to GitHub, or create another Agent engine.")
            if self.require_continuation:
                prompt += (" End your first response after reading the input and proposing coverage; do not write in that response. "
                           "I will review the proposal and use a separate Continue action before you create the file.")
            self.result["original_prompt"] = prompt
            self.prompt(prompt)
            messages, output, content = self.wait_for_task()
            self.result["transcript"] = transcript_evidence(messages, self.secrets)
            self.result["output_file"] = sanitize_evidence({"name": self.filename, "content": content, "parsed_json": output}, self.secrets)
            if self.require_continuation:
                require(any(item["text"] is None and item["before_approved"] and item["after_approved"] and
                            item["before_intent_hash"] == item["after_intent_hash"] for item in self.result.get("continuations", [])),
                        "The required empty continuation did not preserve an actual approved task")
            require(output == {"group": self.member["group"], "count": 4, "sum": 21, "min": 2, "max": 9, "input_file": "qa-input.json"}, "Actual output file does not match the input calculation")
            require(self.request("GET", "/file/content", query={"path": "qa-input.json"})["content"] == inputs["content"], "The task modified its read-only input fixture")
            user_text = [part.get("text") for message in messages if message.get("info", {}).get("role") == "user"
                         for part in message.get("parts", []) if part.get("type") == "text" and not part.get("synthetic")]
            require(prompt in user_text, "The native transcript did not preserve the original user prompt")
            tools = [part for message in messages for part in message.get("parts", []) if part.get("type") == "tool"]
            completed = [part for part in tools if part.get("state", {}).get("status") == "completed"]
            require(any(part["tool"] in ("write", "edit", "apply_patch") for part in completed), "No native file write completed")
            require(any(part["tool"] == "read" for part in completed), "No native file read completed")
            require(all(part["tool"] not in ("run_agent", "quantcode_run_agent", "spawn_agent_python") for part in tools), "A legacy Agent engine was invoked")
            self.result["tool_calls"] = [{"tool": part["tool"], "status": part.get("state", {}).get("status")} for part in tools]
            self.step("real_native_read_write", filename=self.filename, sha256=hashlib.sha256(content.encode()).hexdigest())
            prefix = f"/experimental/quantcode/session/{self.session_id}"
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                index = self.request("GET", prefix + "/task-index")
                task = index["task"]
                if task["status"] == "completed":
                    break
                time.sleep(2)
            require(task["status"] == "completed", "Native task index does not confirm completion")
            self.result["task"] = {key: task[key] for key in ("source_id", "session_id", "source_revision", "status", "tokens_input", "tokens_output", "artifact_count")}
            require(task["tokens_input"] > 0 and task["tokens_output"] > 0, "Real provider usage was not settled")
            self.step("native_task_completed", **self.result["task"])
            source = quote(task["source_id"], safe="")
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                response = self.client.get(f"/experimental/quantcode/organization-tasks/{source}/{self.session_id}", params={"directory": self.member["workspace"]})
                if response.status_code == 200 and response.json()["task"]["status"] == "completed":
                    task = response.json()["task"]
                    self.step("organization_task_published")
                    break
                time.sleep(2)
            else:
                raise AssertionError("Actual native task was not published to the organization gateway")
            if not task["artifact_count"]:
                self.result["status"] = "partial"
                self.result["blocker"] = "Native file exists, but native write metadata produced no captured artifact in the task index"
            else:
                self.verify_artifacts(task, content)
                self.result["status"] = "passed"
            self.login()
            remembered = self.request("GET", "/global/config", scoped=False)
            require(remembered.get("model") == f"{PROVIDER}/{MODEL}", "Relogin lost the selected model")
            restored = self.request("GET", prefix + "/task-index")
            require(restored["task"]["session_id"] == self.session_id and restored["task"]["status"] == "completed", "Relogin lost the member's own task history")
            self.step("relogin_restores_model_and_history")
            self.verify_relogin_execution()
        except Exception as error:
            self.result["status"] = "failed"
            self.result["blocker"] = sanitize_evidence(str(error) if isinstance(error, AssertionError) else type(error).__name__, self.secrets)
            if self.client and self.session_id:
                try:
                    messages = self.request("GET", f"/session/{self.session_id}/message")
                    self.result["transcript"] = transcript_evidence(messages, self.secrets)
                    self.result["assistant_errors"] = [item["error"] for item in self.result["transcript"] if item.get("error")]
                    self.result["tool_errors"] = [part for item in self.result["transcript"] for part in item["parts"]
                                                  if part.get("type") == "tool" and part.get("status") == "error"]
                except Exception:
                    self.result["diagnostic_error"] = "Could not read the failed native task transcript"
                try:
                    statuses = self.request("GET", "/session/status")
                    stopped = []
                    for session_id in self.created_sessions:
                        if statuses.get(session_id, {}).get("type", "idle") != "idle":
                            self.request("POST", f"/session/{session_id}/abort", {}, allowed=(200, 204))
                            stopped.append(session_id)
                    self.result["cleanup"] = {"stopped_active_test_sessions": stopped, "idle_sessions_and_files_preserved": True}
                except Exception:
                    self.result["cleanup_error"] = "Could not stop the failed QA task"
        return self.result

    def verify_artifacts(self, task, expected_content):
        prefix = f"/experimental/quantcode/organization-tasks/{quote(task['source_id'], safe='')}/{self.session_id}"
        deadline = time.monotonic() + 60
        candidates = []
        while time.monotonic() < deadline:
            task = self.request("GET", prefix)["task"]
            response = self.client.get(prefix + "/artifacts", params={"directory": self.member["workspace"], "source_revision": task["source_revision"]})
            if response.status_code == 200:
                candidates = [item for item in response.json()["artifacts"] if item.get("name") == self.filename and item.get("delivery_status") == "available"]
                if candidates:
                    break
            time.sleep(2)
        require(candidates, "The created file is absent from the organization artifact manifest")
        artifact = candidates[0]
        chunk = self.request("GET", prefix + "/artifacts/" + quote(artifact["id"], safe=""), query={"source_revision": task["source_revision"], "offset": 0})
        data = base64.b64decode(chunk["content"], validate=True)
        require(hashlib.sha256(data).hexdigest() == artifact["sha256"], "Published artifact checksum differs")
        require(data == expected_content.encode(), "Published artifact did not preserve the actual output file")
        self.result["artifact"] = {"id": artifact["id"], "name": artifact["name"], "sha256": artifact["sha256"]}
        self.step("organization_artifact_download", sha256=artifact["sha256"])

    def verify_relogin_execution(self):
        session = self.request("POST", "/session", {"title": f"QA reconnect {self.member['group']} {self.run_id}"})
        session_id = session["id"]
        self.created_sessions.append(session_id)
        self.result["relogin_probe"] = {"session_id": session_id, "status": "pending"}
        self.request("POST", f"/session/{session_id}/prompt_async", {"agent": "build",
            "model": {"providerID": PROVIDER, "modelID": MODEL}, "parts": [{"type": "text", "text":
            "Verify that the published organization capability catalog and group Memory can be read in this login. "
            "Then read qa-input.json and briefly confirm its group. This is read-only; do not write files or propose changes."}]}, allowed=(200, 204))
        deadline = time.monotonic() + min(self.timeout, 120)
        expected = {"quantcode_list_capabilities", "quantcode_search_memory"}
        while time.monotonic() < deadline:
            messages = self.request("GET", f"/session/{session_id}/message")
            self.result["relogin_probe"]["transcript"] = transcript_evidence(messages, self.secrets)
            inspections = [part for message in messages for part in message.get("parts", [])
                           if part.get("type") == "tool" and part.get("tool") in expected]
            self.result["relogin_probe"]["inspections"] = [{"tool": part["tool"], "status": part.get("state", {}).get("status")} for part in inspections]
            require(not any(part.get("state", {}).get("status") == "error" for part in inspections),
                    "Relogin left a stale native MCP identity: organization inspections failed")
            assistants = [message["info"] for message in messages if message["info"]["role"] == "assistant"]
            require(not any(info.get("error") for info in assistants), "Read-only task after relogin failed")
            if assistants and assistants[-1].get("finish") == "stop":
                require(expected <= {part["tool"] for part in inspections if part.get("state", {}).get("status") == "completed"},
                        "Relogin did not re-establish both organization inspection tools")
                self.result["relogin_probe"]["status"] = "passed"
                self.step("relogin_native_mcp_execution")
                return
            time.sleep(1)
        raise AssertionError("Read-only native task after relogin timed out")

    def close(self):
        if self.client:
            try:
                if self.logged_in:
                    self.request("POST", "/experimental/quantcode/identity/logout", {}, scoped=False)
                    identity = self.request("GET", "/experimental/quantcode/identities", scoped=False)
                    require(identity.get("session") is None, "Logout did not clear the live session")
                    denied = self.client.get("/experimental/quantcode/workspaces")
                    require(denied.status_code == 400, "Logout did not revoke workspace discovery")
                    self.step("logout_revokes_access")
            except Exception:
                self.result["status"] = "failed"
                self.result["logout_error"] = "Logout or post-logout access verification failed"
            self.client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--proxy-access", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--groups", default=",".join(GROUPS))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--continuation-mode", choices=("text", "empty"), default="text")
    parser.add_argument("--require-continuation", action="store_true")
    args = parser.parse_args()
    require(1 <= args.workers <= 8 and args.timeout > 0, "Invalid worker count or task timeout")
    manifest = json.loads(args.manifest.read_text())
    require(manifest.get("purpose") == "isolated-eight-group-e2e", "Only an isolated QA deployment manifest is accepted")
    selected = args.groups.split(",")
    require(set(selected) <= set(GROUPS), "Unknown group selection")
    require(len(selected) == len(set(selected)), "Group selections must be unique")
    members = [member for member in manifest["members"] if member["group"] in selected]
    require(len(members) == len(selected), "Manifest is missing a selected group")
    require(len({member["fingerprint"] for member in members}) == len(members), "Each simulated member must have a different SSH identity")
    require(len({member["native_base_url"] for member in members}) == len(members), "Each member must use its own native host")
    for member in members:
        require(member["actor_id"].startswith("sim-") and member["username"].startswith("qc-sim-"), "Refusing a non-simulated member")
        require(PurePosixPath(member["workspace"]).is_relative_to("/srv/quantcode-qa"), "Refusing a production workspace")
        require(urlparse(member["native_base_url"]).hostname == "127.0.0.1", "Use a local SSH tunnel for the QA host")
        require(Path(member["private_key_file"]).resolve().is_relative_to(args.manifest.parent.resolve()), "Test key is outside the QA control directory")
    proxy = private_json(args.proxy_access)
    require(urlparse(proxy["base_url"]).hostname == "127.0.0.1", "QA model proxy must be loopback")
    run_id = uuid.uuid4().hex[:10]
    report = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(), "mode": "real-native-agent-http-e2e",
              "model": MODEL, "synthetic_input": True, "domain_component_acceptance": False,
              "desktop_ui_exercised": False, "continuation_mode": args.continuation_mode, "required_continuation": args.require_continuation,
              "members": [], "cross_member_checks": []}
    with signing_agent(members) as agent_env:
        runners = [Member(member, run_id, proxy, agent_env, args.timeout, args.continuation_mode, args.require_continuation) for member in members]
        try:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                report["members"] = list(pool.map(lambda runner: runner.run(), runners))
            successful = [runner for runner in runners if runner.result["status"] != "failed" and
                          any(step["name"] == "organization_task_published" for step in runner.result["steps"])]
            require(len({runner.result["task"]["source_id"] for runner in successful}) == len(successful), "Independent native hosts must have different publisher identities")
            for reader in successful:
                task = reader.result["task"]
                own = reader.request("GET", f"/experimental/quantcode/organization-tasks/{quote(task['source_id'], safe='')}/{task['session_id']}")
                require(own["task"]["actor_id"] == reader.member["actor_id"], "Own-task read must succeed before cross-member denial checks")
                for owner in successful:
                    if reader is owner:
                        continue
                    task = owner.result["task"]
                    endpoint = f"/experimental/quantcode/organization-tasks/{quote(task['source_id'], safe='')}/{task['session_id']}"
                    confirmed = owner.request("GET", endpoint)["task"]
                    require(confirmed["actor_id"] == owner.member["actor_id"], "Target task must exist and be readable by its actual owner")
                    response = reader.client.get(endpoint, params={"directory": reader.member["workspace"]})
                    denied = response.status_code in (400, 401, 403, 404) and confirmed["title"] not in response.text
                    report["cross_member_checks"].append({"reader": reader.member["group"], "owner": owner.member["group"],
                                                          "resource": "task", "status": "passed" if denied else "failed", "http_status": response.status_code})
                    artifact = owner.result.get("artifact")
                    if artifact:
                        artifact_endpoint = endpoint + "/artifacts/" + quote(artifact["id"], safe="")
                        query = {"source_revision": confirmed["source_revision"], "offset": 0}
                        original = owner.request("GET", artifact_endpoint, query=query)
                        require(original.get("content") is not None, "Target artifact must be downloadable by its actual owner")
                        response = reader.client.get(artifact_endpoint, params={"directory": reader.member["workspace"], **query})
                        denied = response.status_code in (400, 401, 403, 404) and original["content"] not in response.text
                        report["cross_member_checks"].append({"reader": reader.member["group"], "owner": owner.member["group"],
                            "resource": "artifact", "artifact_id": artifact["id"],
                            "status": "passed" if denied else "failed", "http_status": response.status_code})
                    own_task = reader.result["task"]
                    live = reader.request("GET", f"/experimental/quantcode/organization-tasks/{quote(own_task['source_id'], safe='')}/{own_task['session_id']}")
                    require(live["task"]["actor_id"] == reader.member["actor_id"], "Cross-member denial must not be caused by a dead reader login")
        except Exception as error:
            report["cross_member_error"] = str(error) if isinstance(error, AssertionError) else type(error).__name__
        finally:
            for runner in runners:
                runner.close()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["counts"] = {status: sum(member["status"] == status for member in report["members"]) for status in ("passed", "partial", "failed")}
    report["expected_cross_member_checks"] = len(members) * (len(members) - 1) * 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "counts": report["counts"], "cross_member_checks": len(report["cross_member_checks"])}))
    return 0 if report["counts"]["passed"] == len(members) and "cross_member_error" not in report and len(report["cross_member_checks"]) == report["expected_cross_member_checks"] and all(item["status"] == "passed" for item in report["cross_member_checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
