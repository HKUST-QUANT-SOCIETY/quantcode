/** Trusted host CLI. A researcher cannot enroll paths through an Agent tool.
 * The recipient always comes from the live roster session, never CLI group or
 * actor arguments. Log in as the intended member before enrolling a checkout.
 * Keep the complete control directory outside research workspaces.
 *
 * bun script/enroll-quantcode-workspace.ts status
 * bun script/enroll-quantcode-workspace.ts grant /absolute/checkout read|write EXPECTED_DIGEST
 * bun script/enroll-quantcode-workspace.ts revoke /absolute/checkout EXPECTED_DIGEST
 */
import { lstat, realpath } from "node:fs/promises"
import path from "node:path"
import os from "node:os"
import { Global } from "@opencode-ai/core/global"
import { QuantCodeIdentity } from "../src/quantcode/identity"
import { QuantCodeWorkspace } from "../src/quantcode/workspace"
import { digest, readCurrent, privateDirectory, updateHostFile } from "./quantcode-host-file"

const [mode, requested, accessOrExpected, expectedArgument] = process.argv.slice(2)
if (process.env.OPENCODE_CHANNEL !== "quantcode") throw new Error("Run this host CLI with OPENCODE_CHANNEL=quantcode")
if (mode !== "status" && mode !== "grant" && mode !== "revoke") {
  throw new Error("Usage: enroll-quantcode-workspace.ts status | grant ABSOLUTE_ROOT read|write EXPECTED_DIGEST | revoke ABSOLUTE_ROOT EXPECTED_DIGEST")
}
const destination = process.env.QUANTCODE_WORKSPACES_FILE ?? path.join(Global.Path.config, "workspaces.json")
if (!path.isAbsolute(destination)) throw new Error("Workspace configuration destination must be absolute")
await privateDirectory(path.dirname(destination))
if (mode === "status") {
  const content = await readCurrent(destination, 262144)
  const grants = content === undefined ? [] : QuantCodeWorkspace.grantSchema.parse(JSON.parse(content)).grants
  // No member paths, credentials or other members' identifiers are printed.
  process.stdout.write(JSON.stringify({ digest: content === undefined ? "absent" : digest(content), grants: grants.length }) + "\n")
  process.exit(0)
}
if (!requested || !path.isAbsolute(requested) || requested.includes("\0")) throw new Error("Checkout must be an absolute path")
if (mode === "grant" && accessOrExpected !== "read" && accessOrExpected !== "write") throw new Error("Access must be read or write")
const expected = mode === "grant" ? expectedArgument : accessOrExpected
if (!/^(absent|[a-f0-9]{64})$/.test(expected ?? "")) throw new Error("Exact expected digest (or absent) is required")
const identity = await QuantCodeIdentity.currentIdentity()
// Revoke also works after a checkout was removed. It addresses the canonical
// absolute path previously granted, without creating the missing directory.
const root = mode === "grant" ? await realpath(requested) : path.resolve(requested)
if (root !== path.resolve(requested)) throw new Error("Use the canonical checkout path; symlink aliases cannot be enrolled")
if (mode === "grant") {
  const info = await lstat(root)
  if (!info.isDirectory() || info.isSymbolicLink() || info.mode & 0o022 || (process.getuid && info.uid !== process.getuid())) {
    throw new Error("Checkout must be a host-owned directory without group/world write access")
  }
  if (QuantCodeWorkspace.contains(root, os.homedir())) throw new Error("Enroll a specific checkout, not the home directory or its ancestors")
  for (const reserved of QuantCodeWorkspace.privatePaths(root)) {
    if (QuantCodeWorkspace.contains(await QuantCodeWorkspace.canonical(reserved), root)) {
      throw new Error("Credential and organization control directories cannot be enrolled as research workspaces")
    }
  }
}
const result = await updateHostFile({ filename: destination, expected: expected!, maxBytes: 262144, history: "workspace-history",
  update: async previous => {
    const document = previous === undefined ? { version: 1 as const, grants: [] } : QuantCodeWorkspace.grantSchema.parse(JSON.parse(previous))
    const sameRecipient = (entry: (typeof document.grants)[number]) => entry.actor_id === identity.actor_id &&
      entry.group === identity.group && entry.workspace_id === identity.workspace_id
    const remaining = document.grants.filter(entry => !sameRecipient(entry) || entry.root !== root)
    if (mode === "revoke" && remaining.length === document.grants.length) throw new Error("No exact workspace grant exists for the current member")
    const current = await QuantCodeIdentity.currentIdentity()
    if (current.session_id !== identity.session_id ||
        JSON.stringify(QuantCodeIdentity.ownerOf(current)) !== JSON.stringify(QuantCodeIdentity.ownerOf(identity))) {
      throw new Error("Login or roster authorization changed; enrollment was not published")
    }
    if (mode === "grant" && await realpath(requested) !== root) throw new Error("Checkout changed during enrollment")
    return JSON.stringify(QuantCodeWorkspace.grantSchema.parse({ version: 1, grants: mode === "revoke" ? remaining : [
      ...remaining, { actor_id: identity.actor_id, group: identity.group, workspace_id: identity.workspace_id, root, access: accessOrExpected },
    ] }), null, 2) + "\n"
  },
})
process.stdout.write(JSON.stringify({ ...result, mode }) + "\n")
