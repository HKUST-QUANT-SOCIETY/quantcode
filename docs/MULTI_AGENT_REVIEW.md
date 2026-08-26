# QuantCode Multi-Agent Review

Every ready, internal same-repository pull request to `main` is handled by four trusted jobs:

1. `Initialize Quant Review Gate` replaces any prior status on the PR head with `pending`, or `failure` for a draft/cross-repository PR.
2. `Quant Physical Gates` runs deterministic secret, production-path, schema, shell, reproducibility, and test checks.
3. `Quant Multi-Agent Review` routes the diff to six DeepSeek-backed reviewers using trusted configuration from the target branch.
4. `Publish Quant Review Gate` writes the final head-bound `Quant Review Gate` status. It reports success only when both review stages completed successfully.

The central engine is pinned to commit
`374e0176fecb21b1729bf38fcaf205580793afc6` from
`HKUST-QUANT-SOCIETY/multiagent_review_ci_standalone`.

## Fixed Server B runtime

The runner does not create a virtual environment or install QuantCode, OpenCode, or the review engine on every PR. Agent review and host-side deterministic gates call this versioned runtime:

```text
/srv/quant/envs/quant-review-374e0176-a3cd117-v2
```

The review venv contains the exact central-engine wheel and 113 frozen third-party packages resolved from the QuantCode `a3cd117...` dependency baseline. Physical pytest execution uses a separate environment that contains only those third-party dependencies:

```text
/srv/quant/envs/quantcode-testdeps-a3cd117-v1
```

Neither the QuantCode distribution nor the private central review engine is installed in that test environment; tests import the PR checkout. Python 3.12.13 comes from an admin-owned stable base, so PR code cannot modify the interpreter. The workflow supplies that base's explicit, read-only `LD_LIBRARY_PATH`.

The runtime was rebuilt without network access from a 115-wheel, individually hashed, admin-only wheelhouse at:

```text
/srv/quant/envs/quant-review-wheelhouse-374e0176-a3cd117
```

The wheelhouse includes the central engine and a provenance-only QuantCode wheel. It is not mounted into PR jobs. The fixed MimoCode commit `0abfd8a...` contributes a separate read-only compose bundle with 38 fully hashed files, including 15 `SKILL.md` files.

Tracked audit copies:

- [`MULTI_AGENT_REVIEW_RUNTIME.json`](MULTI_AGENT_REVIEW_RUNTIME.json) — OS/ABI, source refs, wheel/runtime hashes, model cache, ACL, and test evidence;
- [`MULTI_AGENT_REVIEW_TEST_SANDBOX.json`](MULTI_AGENT_REVIEW_TEST_SANDBOX.json) — isolated test-dependency inventory, wrapper hash, mount/cgroup limits, and sandbox evidence;
- [`MULTI_AGENT_REVIEW_REQUIREMENTS.txt`](MULTI_AGENT_REVIEW_REQUIREMENTS.txt) — exact third-party pins;
- [`MULTI_AGENT_REVIEW_WHEELHOUSE_SHA256SUMS`](MULTI_AGENT_REVIEW_WHEELHOUSE_SHA256SUMS) — SHA-256 for every offline wheel.

Two public model assets needed by the offline test suite are also pre-provisioned and hash checked: tiktoken `cl100k_base` and Chroma `all-MiniLM-L6-v2`. Tests never download either asset during a PR.

Before reading PR files, both jobs verify:

- the manifest SHA-256;
- the frozen `runtime-requirements.txt` SHA-256;
- the `pip inspect` inventory SHA-256;
- the admin-owned Python executable and `libpython` SHA-256 values;
- the configured 40-character `REVIEW_CI_REF` against the manifest;
- that `quant-review-ci` starts successfully.

Before physical tests, the workflow additionally verifies the separate test requirements, `pip inspect`, freeze inventory, sandbox manifest, wrapper, stable Python link, cgroup values, and 6 GiB tmpfs capacity. It runs `pip check` and proves that neither QuantCode nor the central review engine is installed in the test venv.

Updating the review engine or dependency baseline means building a new versioned directory and changing the workflow through a reviewed PR. Never overwrite an in-use runtime in place.

## Trust boundary

- The `quant-review-runners` group is restricted to selected private repositories.
- The persistent Server B runner is not enabled for the public `opencode` repository. Status-only initializer/publisher jobs may run for fork, draft, or closed PR events solely to invalidate the advisory status; they never check out or execute that PR source.
- The workflow uses `pull_request_target`, so its executable YAML and GitHub-token permissions come from `main`, never from the PR head. The current repository plan does not protect `main`; the resulting trust limitation is documented below.
- Current authorization assumes every repository write collaborator is trusted with DeepSeek review access and the Server B review capability. PR contents remain untrusted for code execution. If that collaborator assumption is false, withhold `DEEPSEEK_API_KEY` until protected `main` and a dedicated attestor are available.
- Physical and agent jobs run only when the PR head repository exactly equals `HKUST-QUANT-SOCIETY/quantcode`, the PR is open, and it is ready for review.
- The physical job receives no provider secret.
- The agent job receives `DEEPSEEK_API_KEY` only through the `deepseek-review` environment.
- PR source is untrusted input. The executable review runtime comes from the fixed Server B venv, not the PR.
- Both stages check out the PR at the event's exact head SHA, while repository-specific `.review-ci` configuration is checked out separately from the exact base SHA. Neither checkout persists credentials. The workflow verifies both resulting SHAs, rejects every PR symlink and any tracked path containing control characters, backslashes, or double quotes before host-side inspection, and fails if target-branch `.review-ci` is absent or incomplete. This closes ambiguous-path gaps in the pinned engine's non-NUL Git parser; the engine should still migrate to NUL-delimited parsing upstream.
- The physical artifact is bound to the same repository, workflow run, base SHA, and head SHA before the agent stage consumes it.
- GitHub token capabilities are job-scoped: the physical stage has read-only contents access; the agent stage can read its same-run artifact and maintain one issue comment; and only the initializer/final publisher can write commit statuses.
- The final publisher re-reads the live PR, verifies that its head/base SHAs plus open/draft state still match the event, then writes `Quant Review Gate` to the PR head SHA. Internal `pull_request_target` job checks are anchored to the base commit and are not head-bound merge checks.

The physical policy is allowed to execute the target branch's trusted test command against private same-repository PR code. The command copies the checkout onto a dedicated 6 GiB `tmpfs`, then enters a minimal chroot with user, mount, PID, network, IPC, and UTS namespaces. It mounts only selected system directories (excluding `/usr/local`), public CA files, the stable Python/test dependencies, fixed skills, and fixed model caches as read-only `nosuid,nodev` inputs. It does not mount the host's `/etc`, runner installation, runner HOME, central review engine, unrelated `/srv/quant` paths, or network. After mounting, it sets `no_new_privs`, drops the capability bounding set, and applies CPU, virtual-memory, process, file, descriptor, and core limits. The runner service also enforces `MemoryHigh=8G`, `MemoryMax=10G`, no swap, `TasksMax=768`, `CPUQuota=400%`, and `KillMode=control-group`; `OOMPolicy=kill` plus `Restart=always` restarts the process after 10 seconds. A controlled whole-cgroup kill recovered one conflict-free listener; GitHub released the old broker session and returned to `Listening for Jobs` after about 71 seconds. Wrapper startup safely removes only runner-owned `quantcode-pytest.*` residue from the dedicated tmpfs, and a stale-directory smoke passed.

The agent stage does not execute PR code and accepts only the approved `https://api.deepseek.com` endpoint with proxy, custom CA, user-site, and injected Python-path variables removed. It sends the private PR diff and review context to DeepSeek; it does not send GitHub, COS, deployment, or Server B credentials.

## Reviewer matrix

| Reviewer | Routed categories | Main responsibility |
| --- | --- | --- |
| Schema Contract | `contracts`, `integration` | Typed producer/consumer compatibility and cross-group schemas |
| Agent Orchestration | `orchestration`, `memory`, `integration` | Routing, retries, checkpoints, Memory/Blackboard isolation, HumanGate resume |
| Quant Research Integrity | `factor`, `model`, `fundamental`, `strategy`, `options` | PIT safety, leakage, reproducibility, costs, execution timing |
| Risk and HumanGate | `risk`, `orchestration`, `contracts` | Risk thresholds, fail-closed admission, decision/head-SHA binding |
| CI and Supply Chain | `ci`, `integration` | Actions, runner/secrets boundaries, pinned runtime, fail-closed gates |
| Documentation and Operations | `docs`, `ci`, `unknown` | Docs/config consistency, ownership, validation, rollback |

The complete definitions live in `.review-ci/reviewer_matrix.yaml`. Every reviewer has a mission, blocker/important rules, loaded skills, deterministic gate bindings, a specialist subagent, and changed-file evidence verification.

## Deterministic gate policy

`.review-ci/gate_policy.yaml` defines the physical checks:

- `secret_gate`, `prod_path_gate`, `schema_gate`, and `shell_syntax_gate` are required.
- `pytest_gate` calls the hash-pinned isolation wrapper for code/config changes and blocks when the 597-test suite fails. It may skip a docs-only PR.
- `reproducibility_gate` checks research randomness and wall-clock dependence; important findings warn while blocker findings stop the review.
- QuantCode has several domain artifact schemas, not one universal manifest. The generic artifact gate remains disabled instead of asserting a false common contract.

Trusted workflow preflight supplements the pinned engine: it rejects ambiguous/non-printable or credential-like Git paths, symlinks, more than 500 changed files, a patch above 120,000 bytes, any blob above 20 MiB, or a tree above 512 MiB. It also scans the complete contents of every added/changed blob for the engine's credential patterns, avoiding the engine's per-file 200,000-character scan cap. The 120,000-byte patch ceiling is conservative so no reviewer receives a silently truncated diff; larger changes must be split.

The repository's `uv.lock` is not used as proof of the Server B environment because it does not currently describe every dependency in `pyproject.toml`. The runtime records the actual resolved set in its hashed `runtime-requirements.txt`.

## Rollout and current enforcement

GitHub intentionally does not execute a new `pull_request_target` workflow from the PR that introduces it, because that definition is not yet on `main`. Review the deployment PR statically, merge it with explicit project-lead approval, and then validate a second minimal PR.

After the workflow and `.review-ci` configuration are merged:

1. open a minimal same-repository test PR;
2. verify the job log identifies the exact target-branch SHA used for `.review-ci`;
3. verify all six reviewer names appear in the combined result;
4. verify the PR summary marker is updated rather than duplicated;
5. verify the explicit `Quant Review Gate` commit status is attached to the current PR head SHA and points to the matching workflow run;
6. verify draft conversion publishes failure and a subsequent ready event writes pending before re-review.

The workflow listens for `edited` only to handle base-branch retargeting; title/body edits do not rerun 597 tests or start six additional DeepSeek reviewer pipelines.

As of 2026-08-24, `HKUST-QUANT-SOCIETY` is on GitHub Free and `quantcode` is private. GitHub's API reports `main` as unprotected and rejects private-repository branch protection/rulesets with an upgrade requirement. Therefore `Quant Review Gate` is currently an **advisory status**, not an enforceable merge gate. A write collaborator can also create another workflow that publishes the same GitHub Actions status context. Because both status writers queue on Server B, an offline/busy runner can temporarily leave an older advisory success visible, and cancellation races are not a hard security boundary.

Before calling this a hard gate, upgrade to a plan that supports private-repository protection, disable direct pushes, require PRs and strict up-to-date branches (or a compatible merge queue), and publish the required status from a dedicated GitHub App or organization-level required workflow. The initializer must then run through that independent attestor so an offline Server B cannot leave a reusable old success. Require only the dedicated head-bound context; do not require the three internal base-anchored job checks.

## Peer Server B Risk Gate

`Risk Gate` is a separate, logically peer workflow on the same `quant-review-runners` group and `server-b-multiagent-review` label. It does not replace repository-wide multi-agent review, and neither workflow depends on the other's conclusion. With one registered listener the two workflows queue on the same machine; true simultaneous execution requires a second matching runner.

The risk workflow follows the same trust split:

- `pull_request_target` loads executable YAML from trusted `main`.
- The planner reads the exact PR head only as bounded Git data; planner code, schemas, capability registry and workflow authority come from the exact base SHA.
- A newly spawned Risk Scout subagent uses only `list_changed_files`, `read_changed_files`, capability lookup, policy lookup and `submit_risk_gate_task`. Provider egress is limited to changed-file diffs and trusted capability/policy metadata; unmodified private source is not exposed. The scout has no shell, write, GitHub, raw-data or HumanGate tool.
- The scout dynamically returns `required | not_required | indeterminate`, open-ended risk domains, included/excluded scope, a step DAG, evidence requirements and structured capability requests. `not_required` still requires complete diff coverage and an Artifact.
- Trusted validation injects the repository/PR/base/head binding, verifies evidence references and canonical SHA-256, and resolves capability ids. Unknown or unavailable capabilities remain visible but cannot execute.
- Only an execution-ready plan reaches the offline executor. The executor receives no DeepSeek key or GitHub token and dispatches only root-owned, digest-pinned handlers/data snapshots. The current registry has one execution-ready single-asset backtest capability; other dynamically planned checks fail closed as `not_evaluable` until a bounded handler exists.
- Current v1 binds exactly one required step/request to one evidence Artifact. A multi-step DAG is retained in the task Artifact but is `not_evaluable` until a trusted DAG dispatcher exists. `needs_human` currently publishes an advisory failure; interactive HumanGate approve/resume is not yet connected to this workflow.
- A no-secret reducer binds evidence and policy to the task/plan/head, then a checkout-free publisher revalidates the complete Artifact, upserts one bot-authored report and publishes the head-bound `Quant Risk Gate` status.

The dynamic part is the business scope and process. Fixed parts are secrets isolation, sandboxing, tool/capability permissions, resource limits, Artifact schemas, evidence hashes, live-head checks and HumanGate binding. DeepSeek never directly controls a GitHub status or approval.

This remains an **advisory engineering Risk Gate**, not production investment approval. `RiskProfile` and the old `normal/high_risk` scenarios are legacy fixtures/attachments, not the production orchestration contract.

## GitHub and Server B configuration

Required repository variables:

```text
REVIEW_CI_REF=374e0176fecb21b1729bf38fcaf205580793afc6
REVIEW_CI_PROFILE=quantcode
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

`deepseek-review` stores `DEEPSEEK_API_KEY` and is restricted to the `main` deployment branch. The Server B service uses the low-privilege `gha-multiagent-review` account and runner labels `self-hosted`, `linux`, `x64`, and `server-b-multiagent-review`. Admin-owned runtime, Python, and skill files grant that runner explicit read/execute ACLs; other Server B users have no access.

Repeated draft/ready/reopen events can still intentionally consume provider requests despite per-PR concurrency cancellation. Configure a hard DeepSeek account/project spend cap and usage alerts before enabling review for the wider team.

### Server B resource-unit install map

The tracked units are source files, not their final systemd names:

```text
deploy/server_b/quant-review-sandboxes.mount
  -> /etc/systemd/system/srv-quant-runner\x2dsandboxes.mount
deploy/server_b/quant-review-runner-resource-limits.conf
  -> /etc/systemd/system/actions.runner.HKUST-QUANT-SOCIETY.server-b-multiagent-review-01.service.d/20-review-resource-limits.conf
```

Before installation, `id -u gha-multiagent-review` and `id -g gha-multiagent-review` must return `1042` and `1050`, matching the tmpfs mount options. If a rebuilt host uses different IDs, update the tracked unit and both attestation hashes through review first. Install the two files at the mapped paths as root with mode `0644`, create `/srv/quant/runner-sandboxes`, then run `systemctl daemon-reload`, enable/start the escaped mount unit, and restart the runner service. Verify the tmpfs is exactly 6 GiB with `nosuid,nodev,noexec`; verify cgroup memory/swap/PID/CPU values, `KillMode=control-group`, `OOMPolicy=kill`, `Restart=always`, exactly one `Runner.Listener`, and a fresh `Listening for Jobs` log line.

Rollback installs the previous reviewed unit/drop-in versions, reloads systemd, and restarts the runner. Stop the runner and confirm no job is active before changing or unmounting the sandbox tmpfs; never remove an in-use mount or overwrite a versioned runtime asset.

## Failure interpretation

- `queued` with no steps means no eligible runner accepted the job; inspect Runner Group access, labels, and online state.
- a missing or mismatched manifest/runtime/test-sandbox hash is an infrastructure failure and makes the review status fail.
- physical `block` means deterministic policy failed; agent review does not run.
- agent error, abnormal skip, invalid JSON, missing result, or stale artifact makes the final status fail.
- draft PRs, fork PRs, skipped stages, and non-success job conclusions publish a failing head-bound gate when the trusted publisher runs.
- `warn` remains visible but does not block unless policy promotes it.
- the review jobs run on Server B; unrelated GitHub-hosted CI billing/queues must not be diagnosed as a DeepSeek failure.

## Updating the runtime

Build a new review runtime and a separate engine-free test-dependency venv from a reviewed engine commit and QuantCode dependency baseline. Preserve an offline wheelhouse with a SHA-256 entry for every wheel; install only from that verified wheelhouse. Record the engine/tree refs, QuantCode dependency commit, Python/ABI/OpenSSL/glibc identity, project wheel provenance, Python binary hashes, both manifests, frozen requirements, both `pip inspect` inventories, wheelhouse lock, full MimoCode bundle hash, host limits, and test evidence. Validate imports, configuration loading, `quant-review-ci --help`, both `pip check` runs, ELF dependencies, cgroup/tmpfs values, and the QuantCode test suite before removing write permission and applying the runner read-only ACL.

Rollback is a normal workflow revert to the previous immutable runtime path and engine SHA.
