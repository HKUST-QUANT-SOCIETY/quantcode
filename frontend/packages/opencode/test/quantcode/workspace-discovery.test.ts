import { expect, test } from "bun:test"
import { once } from "node:events"
import { createServer } from "node:http"
import { chmod, mkdir, writeFile } from "node:fs/promises"
import path from "node:path"
import { tmpdir } from "../fixture/fixture"
import { QuantCodeIdentity } from "../../src/quantcode/identity"
import { QuantCodeWorkspace } from "../../src/quantcode/workspace"

// A small HTTP authority isolates workspace discovery; signature verification
// and roster admission are covered by the separate gateway integration suite.
async function discovery(run: (input: {
  root: string; control: string; mapped: string; child: string; other: string;
  identity: QuantCodeIdentity.Identity; grants: string;
  onIdentity: (callback: () => Promise<void>) => void;
}) => Promise<void>) {
  await using directory = await tmpdir()
  const control = path.join(directory.path, "control")
  const mapped = path.join(directory.path, "checkout")
  const child = path.join(mapped, "project")
  const other = path.join(directory.path, "other-member")
  for (const folder of [control, mapped, child, other]) await mkdir(folder, { mode: 0o700 })
  const identity: QuantCodeIdentity.Identity = {
    session_id: "a".repeat(32), actor_id: "member-one", group: "factor", role: "analyst",
    workspace_id: "member-workspace", workspace_path: path.join(directory.path, "remote-only"),
    resource_scopes: ["workspace:read", "workspace:write"], authorized_groups: ["factor"],
    issued_at: new Date().toISOString(), expires_at: new Date(Date.now() + 60_000).toISOString(),
    identity_source: "ssh_roster",
  }
  let onIdentity = async () => {}
  const server = createServer((_request, response) => {
    void onIdentity().then(() => {
      response.writeHead(200, { "content-type": "application/json" })
      response.end(JSON.stringify(identity))
    }).catch(() => { response.writeHead(500); response.end() })
  })
  server.listen(0, "127.0.0.1")
  await once(server, "listening")
  const address = server.address()
  if (!address || typeof address === "string") throw new Error("Missing isolated authority address")
  const credential = path.join(control, "identity.json")
  const grants = path.join(control, "workspaces.json")
  await writeFile(credential, JSON.stringify({ gateway: `http://127.0.0.1:${address.port}`, token: "fixture-only-token" }), { mode: 0o600 })
  await writeFile(grants, JSON.stringify({ version: 1, grants: [
    { actor_id: identity.actor_id, group: identity.group, workspace_id: identity.workspace_id, root: mapped, access: "write" },
    { actor_id: "member-two", group: identity.group, workspace_id: identity.workspace_id, root: other, access: "write" },
    { actor_id: identity.actor_id, group: identity.group, workspace_id: identity.workspace_id, root: control, access: "read" },
  ] }), { mode: 0o600 })
  const previous = { session: process.env.QUANTCODE_IDENTITY_SESSION_FILE, grants: process.env.QUANTCODE_WORKSPACES_FILE }
  process.env.QUANTCODE_IDENTITY_SESSION_FILE = credential
  process.env.QUANTCODE_WORKSPACES_FILE = grants
  try {
    await run({ root: directory.path, control, mapped, child, other, identity, grants,
      onIdentity: callback => { onIdentity = callback } })
  } finally {
    if (previous.session === undefined) delete process.env.QUANTCODE_IDENTITY_SESSION_FILE
    else process.env.QUANTCODE_IDENTITY_SESSION_FILE = previous.session
    if (previous.grants === undefined) delete process.env.QUANTCODE_WORKSPACES_FILE
    else process.env.QUANTCODE_WORKSPACES_FILE = previous.grants
    server.closeAllConnections()
    if (server.listening) await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
  }
}

test("first-run discovery uses authorized host roots and excludes other members and control files", () => discovery(async input => {
  const result = await QuantCodeWorkspace.list({ preferred: input.other })
  expect(result).toEqual({ login_session_id: input.identity.session_id,
    roots: [{ directory: input.mapped, access: "write" }] })
  expect(JSON.stringify(result)).not.toContain(input.other)
  expect(JSON.stringify(result)).not.toContain(input.control)
  const selected = await QuantCodeWorkspace.list({ preferred: input.child, expected_session_id: result.login_session_id })
  expect(selected.preferred).toBe(input.child)
}))

test("discovery does not invent a local root for a remote-only roster workspace", () => discovery(async input => {
  await writeFile(input.grants, JSON.stringify({ version: 1, grants: [] }))
  expect((await QuantCodeWorkspace.list()).roots).toEqual([])
}))

test("a picker bound to an older login cannot submit under a new login", () => discovery(async input => {
  await expect(QuantCodeWorkspace.list({ preferred: input.child, expected_session_id: "b".repeat(32) }))
    .rejects.toThrow("登录身份已变化")
}))

test("discovery rejects grants withdrawn while the authority was responding", () => discovery(async input => {
  let requests = 0
  input.onIdentity(async () => {
    if (++requests === 2) await writeFile(input.grants, JSON.stringify({ version: 1, grants: [] }))
  })
  await expect(QuantCodeWorkspace.list({ preferred: input.child })).rejects.toThrow("工作区授权已变化")
}))

test("an unreadable cached subdirectory is not selected as the preferred workspace", () => discovery(async input => {
  await chmod(input.child, 0o000)
  try {
    expect((await QuantCodeWorkspace.list({ preferred: input.child })).preferred).toBeUndefined()
  } finally { await chmod(input.child, 0o700) }
}))

test("discovery rechecks filesystem permissions before returning workspace choices", () => discovery(async input => {
  let requests = 0
  input.onIdentity(async () => {
    if (++requests === 2) await chmod(input.child, 0o000)
  })
  try {
    await expect(QuantCodeWorkspace.list({ preferred: input.child })).rejects.toThrow("工作区授权已变化")
  } finally { await chmod(input.child, 0o700) }
}))
