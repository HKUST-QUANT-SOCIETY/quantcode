/** Host-only, exact-source ownership registration for old native history.
 * Run from packages/opencode; this script is never an HTTP or model tool.
 *
 * bun script/import-quantcode-native-history.ts ABSOLUTE_DB list
 * bun script/import-quantcode-native-history.ts ABSOLUTE_DB preview ROOT_ID
 * bun script/import-quantcode-native-history.ts ABSOLUTE_DB export ROOT_ID ABSOLUTE_PRIVATE_FILE
 * bun script/import-quantcode-native-history.ts ABSOLUTE_DB bind ABSOLUTE_DECLARATION DECLARATION_SHA256
 */
import { lstat, open, realpath } from "node:fs/promises"
import path from "node:path"
import { Effect, Layer } from "effect"
import { Database } from "@opencode-ai/core/database/database"
import { EventV2 } from "@opencode-ai/core/event"
import { QuantCodeIdentity } from "../src/quantcode/identity"
import { QuantCodeUnboundSession } from "../src/quantcode/unbound-session"
import { readPrivateFile } from "../src/quantcode/private-file"
import { digest, writeNewPrivateFile } from "./quantcode-host-file"

const [filename, mode, requested, argument] = process.argv.slice(2)
if (!QuantCodeIdentity.enabled()) throw new Error("Use the explicit QuantCode host migration switches")
if (!filename || !path.isAbsolute(filename) || await realpath(filename) !== filename || process.platform === "win32") {
  throw new Error("Use an existing canonical private native database on a supported host")
}
if (!["list", "preview", "export", "bind"].includes(mode)) throw new Error("Expected list, preview, export or bind")
const initial = await lstat(filename)
const parent = path.dirname(filename)
const directory = await lstat(parent)
if (!initial.isFile() || initial.nlink !== 1 || initial.mode & 0o077 || directory.mode & 0o077 ||
  (process.getuid && (initial.uid !== process.getuid() || directory.uid !== process.getuid()))) {
  throw new Error("Database and its parent must be private and owned by this host account")
}
const identity = await QuantCodeIdentity.currentIdentity()
const unchanged = async () => {
  const current = await QuantCodeIdentity.currentIdentity()
  const file = await lstat(filename)
  if (current.session_id !== identity.session_id ||
    QuantCodeUnboundSession.digest(QuantCodeIdentity.ownerOf(current)) !== QuantCodeUnboundSession.digest(QuantCodeIdentity.ownerOf(identity)) ||
    await realpath(filename) !== filename || file.dev !== initial.dev || file.ino !== initial.ino) {
    throw new Error("Roster identity or source database changed during historical import")
  }
}
const privateControlFile = (value: string) => {
  if (!path.isAbsolute(value) || path.resolve(value) !== value || !value.startsWith(parent + path.sep) || value === filename) {
    throw new Error("History exports, evidence and declarations must be private files inside the native database control directory")
  }
  return value
}
const readLayer = Database.layerFromExistingPath(filename, { readonly: true })
if (mode === "list") {
  const result = await Effect.runPromise(QuantCodeUnboundSession.list.pipe(Effect.provide(readLayer)))
  await unchanged()
  process.stdout.write(JSON.stringify({ read_only: true, sessions: result }) + "\n")
} else if (mode === "preview" || mode === "export") {
  if (!requested) throw new Error("An exact root session ID is required")
  const source = await Effect.runPromise(QuantCodeUnboundSession.inspect(requested).pipe(Effect.provide(readLayer)))
  await unchanged()
  if (mode === "export") {
    if (!argument) throw new Error("A new private output path is required")
    await writeNewPrivateFile(privateControlFile(argument), JSON.stringify(source, null, 2) + "\n")
  }
  process.stdout.write(JSON.stringify({ ...QuantCodeUnboundSession.summary(source), read_only: true }) + "\n")
} else {
  if (!requested || !/^[a-f0-9]{64}$/.test(argument ?? "")) throw new Error("An explicit declaration file and its exact SHA-256 are required")
  const sourceFile = privateControlFile(requested)
  const content = await readPrivateFile(sourceFile, 262144)
  if (digest(content) !== argument) throw new Error("Declaration bytes changed; review the exact file before binding")
  const declaration = QuantCodeUnboundSession.Declaration.parse(JSON.parse(content))
  const evidenceFile = privateControlFile(declaration.evidence_file)
  const evidence = await readPrivateFile(evidenceFile, 1_000_000)
  if (digest(evidence) !== declaration.evidence_digest || !evidence.trim()) throw new Error("Ownership evidence differs from the explicit declaration")
  if (QuantCodeUnboundSession.digest(declaration.owner) !== QuantCodeUnboundSession.digest(QuantCodeIdentity.ownerOf(identity))) {
    throw new Error("Log in as the explicitly declared original member; the CLI will not infer or replace the owner")
  }
  const source = await Effect.runPromise(QuantCodeUnboundSession.inspect(declaration.root_session_id).pipe(Effect.provide(readLayer)))
  if (QuantCodeUnboundSession.digest(source) !== declaration.source_digest) throw new Error("Historical source changed before binding")
  // Preserve review materials before changing metadata. Files are content
  // addressed, private, non-overwriting and never loaded as instructions.
  const archive = path.join(parent, "native-history-imports")
  for (const [name, value] of [
    [`${declaration.source_digest}.source.json`, JSON.stringify(source, null, 2) + "\n"],
    [`${argument}.declaration.json`, content], [`${declaration.evidence_digest}.evidence.txt`, evidence],
  ]) {
    const destination = path.join(archive, name)
    const exists = await lstat(destination).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined
      throw error
    })
    if (!exists) await writeNewPrivateFile(destination, value)
    else if (await readPrivateFile(destination, Math.max(1_000_000, Buffer.byteLength(value))) !== value) {
      throw new Error("Historical import archive conflicts with the reviewed source")
    }
  }
  const archived = await open(archive, "r")
  try { await archived.sync() } finally { await archived.close() }
  const revalidate = async () => {
    await unchanged()
    if (await readPrivateFile(sourceFile, 262144) !== content || await readPrivateFile(evidenceFile, 1_000_000) !== evidence) {
      throw new Error("Ownership declaration or evidence changed before commit")
    }
  }
  const database = Database.layerFromExistingPath(filename, { readonly: false })
  const services = Layer.merge(database, EventV2.layer.pipe(Layer.provide(database)))
  const result = await Effect.runPromise(QuantCodeUnboundSession.bind(declaration, argument!, identity, revalidate)
    .pipe(Effect.provide(services)))
  process.stdout.write(JSON.stringify(result) + "\n")
}
