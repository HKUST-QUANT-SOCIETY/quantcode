import path from "node:path"
import { constants } from "node:fs"
import { open, mkdir, link, rm, lstat, realpath } from "node:fs/promises"
import { createHash, randomUUID } from "node:crypto"
import { Effect, Schema } from "effect"
import { and, asc, eq, inArray, sql } from "drizzle-orm"
import { Database } from "@opencode-ai/core/database/database"
import { EventTable } from "@opencode-ai/core/event/sql"
import { Global } from "@opencode-ai/core/global"
import { QuantCodeTaskIndex } from "@opencode-ai/schema/quantcode-task-index"
import { EventV2Bridge } from "@/event-v2-bridge"
import { SessionID } from "@/session/schema"
import { QuantCodeAccess } from "./access"
import { QuantCodeIdentity } from "./identity"
import { QuantCodeToolCatalog } from "./tool-catalog"
import { QuantCodeWorkspace, type WorkspaceGrant } from "./workspace"

export const CHUNK_BYTES = 64 * 1024
const directory = path.join(Global.Path.data, "artifact-snapshots")
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}
const hash = (value: Uint8Array) => createHash("sha256").update(value).digest("hex")
const safeName = (value: unknown) => {
  if (typeof value !== "string") return undefined
  // A resource URI can contain a credential-bearing query. It may supply a
  // display basename, never its authority, query or fragment.
  const source = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(value) ? (() => {
    try { return new URL(value).pathname } catch { return "" }
  })() : value
  const name = path.basename(source.replaceAll("\\", "/")).replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0, 256)
  return name && name !== "." && name !== ".." ? name : undefined
}
const mimeType = (value: unknown) => typeof value === "string" && /^[\w!#$&^_.+-]+\/[\w!#$&^_.+-]+$/.test(value) && value.length <= 256
  ? value : "application/octet-stream"

type Candidate = { name?: string; mime: string; kind: "artifact" | "report"; source: "attachment" | "metadata";
  path?: string; data?: Buffer; sha256?: string; bytes?: number; invalid?: boolean }

function decoded(value: string, encoding: string) {
  if (encoding !== "base64") return Buffer.from(decodeURIComponent(value), "utf8")
  const bytes = Buffer.from(value, "base64")
  if (bytes.toString("base64") !== value) throw new Error("invalid base64")
  return bytes
}

/** Only explicit artifact fields or actual inline attachments count. Tool logs
 * and arbitrary outputPaths are not reports and are never dereferenced. */
function candidates(raw: unknown): Candidate[] {
  const result = object(raw)
  if (result.isError) return []
  let structured = object(result.structuredContent)
  if (!Object.keys(structured).length && Array.isArray(result.content) && result.content.length === 1) {
    const block = object(result.content[0])
    if (block.type === "text" && typeof block.text === "string") {
      try { structured = object(JSON.parse(block.text)) } catch { /* Ordinary tool text is not artifact metadata. */ }
    }
  }
  const metadata = object(result.metadata)
  const refs = [result.artifacts, structured.artifacts, metadata.artifacts].flatMap(value => Array.isArray(value) ? value : [])
  const artifacts: Candidate[] = refs.map(value => {
    const ref: Record<string, unknown> = typeof value === "string" ? { path: value } : object(value)
    const item: Candidate = {
      name: safeName(ref.name ?? ref.filename ?? ref.path),
      mime: mimeType(ref.mime ?? ref.mimeType),
      kind: ref.kind === "report" ? "report" : "artifact", source: "metadata",
      ...(typeof ref.path === "string" ? { path: ref.path } : {}),
      ...(typeof ref.sha256 === "string" ? { sha256: ref.sha256 } : {}),
      ...(typeof ref.bytes === "number" ? { bytes: ref.bytes } : {}),
    }
    if (typeof ref.content === "string" && ["utf8", "base64"].includes(String(ref.encoding))) {
      try { item.data = ref.encoding === "utf8" ? Buffer.from(ref.content, "utf8") : decoded(ref.content, "base64") }
      catch { item.invalid = true }
    }
    return item
  })
  for (const value of Array.isArray(result.attachments) ? result.attachments : []) {
    const attachment = object(value)
    const item: Candidate = { name: safeName(attachment.filename), mime: mimeType(attachment.mime), kind: "artifact", source: "attachment" }
    if (typeof attachment.url === "string" && attachment.url.startsWith("data:")) {
      const comma = attachment.url.indexOf(",")
      try {
        if (comma < 0) throw new Error("invalid data URL")
        item.data = decoded(attachment.url.slice(comma + 1), attachment.url.slice(5, comma).split(";").includes("base64") ? "base64" : "utf8")
      } catch { item.invalid = true }
    }
    artifacts.push(item)
  }
  for (const value of Array.isArray(result.content) ? result.content : []) {
    const block = object(value)
    if (block.type === "image" || block.type === "audio") {
      const item: Candidate = { mime: mimeType(block.mimeType), kind: "artifact", source: "attachment" }
      try { item.data = decoded(String(block.data), "base64") } catch { item.invalid = true }
      artifacts.push(item)
    }
    if (block.type === "resource") {
      const resource = object(block.resource)
      const item: Candidate = { name: safeName(resource.uri), mime: mimeType(resource.mimeType), kind: "artifact", source: "attachment" }
      try {
        if (typeof resource.blob === "string") item.data = decoded(resource.blob, "base64")
        else if (typeof resource.text === "string") item.data = Buffer.from(resource.text, "utf8")
      } catch { item.invalid = true }
      artifacts.push(item)
    }
  }
  return artifacts
}

async function save(item: Candidate, grant: WorkspaceGrant) {
  await mkdir(directory, { recursive: true, mode: 0o700 })
  const temporary = path.join(directory, `${randomUUID()}.tmp`)
  const output = await open(temporary, "wx", 0o600)
  const source = !item.data && item.path ? await QuantCodeWorkspace.openFile(grant, item.path).catch(() => undefined) : undefined
  try {
    if (!item.data && !source) throw new Error("original bytes unavailable")
    const digest = createHash("sha256")
    let bytes = 0
    const chunks = source ? source.handle.createReadStream({ autoClose: false }) : [item.data!]
    for await (const chunk of chunks) {
      const data = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
      digest.update(data)
      bytes += data.byteLength
      await output.writeFile(data)
    }
    if (source) await source.validate()
    const sha256 = digest.digest("hex")
    if ((item.sha256 !== undefined && item.sha256 !== sha256) || (item.bytes !== undefined && item.bytes !== bytes))
      throw new Error("declared artifact digest or size mismatch")
    await output.sync()
    await output.close()
    // link is create-if-absent; a prior immutable object is never replaced.
    await link(temporary, path.join(directory, sha256)).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== "EEXIST") throw error
    })
    return { bytes, sha256 }
  } finally {
    await source?.close()
    await output.close().catch(() => {})
    await rm(temporary, { force: true })
  }
}

/** Invoke with the direct trusted tool return, before plugin formatting. The
 * original native event log owns provenance; this is not another task store.
 * Retried write receipts reuse this exact event and never reopen its paths. */
export const capture = Effect.fn("QuantCodeArtifacts.capture")(function* (input: {
  sessionID: string; messageID: string; callID: string; result: unknown; fresh?: boolean;
}) {
  if (!QuantCodeIdentity.enabled()) return
  const access = yield* QuantCodeAccess.requireSession(input.sessionID)
  if (!access) throw new QuantCodeIdentity.IdentityError()
  const resultDigest = QuantCodeToolCatalog.digest(input.result)
  const { db } = yield* Database.Service
  const existing = () => db.select({ data: EventTable.data }).from(EventTable)
    .where(and(eq(EventTable.aggregate_id, input.sessionID), eq(EventTable.type, "quantcode.artifacts.captured.1"),
      sql`json_extract(${EventTable.data}, '$.message_id') = ${input.messageID}`,
      sql`json_extract(${EventTable.data}, '$.call_id') = ${input.callID}`))
    .get().pipe(Effect.orDie)
  const previous = yield* existing()
  if (previous) {
    if (previous.data.result_digest !== resultDigest) throw new Error("原工具调用的产物结果已变化，不能覆盖历史版本。")
    return
  }
  const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(access.directory, "read", access.identity))
  const artifacts: QuantCodeTaskIndex.ArtifactSnapshot[] = []
  for (const [index, item] of candidates(input.result).entries()) {
    const key = QuantCodeToolCatalog.digest([input.sessionID, input.messageID, input.callID, resultDigest, index])
    const common = { id: `artifact_${key}`, name: item.name, mime: item.mime, kind: item.kind, source: item.source }
    const originalMissing = !item.data && !input.fresh
    const saved = item.invalid || originalMissing ? undefined : yield* Effect.promise(() => save(item, grant).catch(() => undefined))
    artifacts.push(saved ? { ...common, ...saved, ref: `snapshot:${saved.sha256}`, capture_status: "available" }
      : { ...common, ref: `unavailable:${key}`, capture_status: "unavailable",
        unavailable_reason: item.invalid ? "invalid_content" : originalMissing ? "original_not_captured" : "capture_failed" })
  }
  yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
  const events = yield* EventV2Bridge.Service
  yield* events.publish(QuantCodeTaskIndex.ArtifactsCaptured, { sessionID: SessionID.make(input.sessionID),
    message_id: input.messageID, call_id: input.callID, result_digest: resultDigest, artifacts, timestamp: Date.now() }, {
    commit: () => Effect.gen(function* () {
      if (yield* existing()) throw new Error("该工具调用已有产物快照。")
    }),
  }).pipe(Effect.catchCause(cause => Effect.gen(function* () {
    const committed = yield* existing()
    if (committed?.data.result_digest === resultDigest) return
    return yield* Effect.failCause(cause)
  })))
})

/** This projection reads immutable events only. Mutable files, paths, current
 * PartTable contents and retention-managed tool logs cannot change a revision. */
export const collect = Effect.fn("QuantCodeArtifacts.collect")(function* (sessionID: string) {
  const { db } = yield* Database.Service
  const rows = yield* db.select().from(EventTable).where(and(eq(EventTable.aggregate_id, sessionID),
    inArray(EventTable.type, ["quantcode.artifacts.captured.1", "message.part.updated.1"])))
    .orderBy(asc(EventTable.seq)).all().pipe(Effect.orDie)
  const captured = new Set(rows.filter(row => row.type === "quantcode.artifacts.captured.1")
    .map(row => JSON.stringify([row.data.message_id, row.data.call_id])))
  const artifacts: QuantCodeTaskIndex.ArtifactRef[] = []
  const inline = new Map<string, Buffer>()
  const seen = new Set<string>()
  for (const row of rows) {
    if (row.type === "quantcode.artifacts.captured.1") {
      const data = Schema.decodeUnknownSync(QuantCodeTaskIndex.ArtifactsCaptured.data)(row.data)
      for (const item of data.artifacts) artifacts.push({ ...item, source_event_id: row.id, source_event_seq: row.seq,
        message_id: data.message_id, call_id: data.call_id, result_digest: data.result_digest })
      continue
    }
    const part = object(row.data.part)
    const state = object(part.state)
    if (part.type !== "tool" || state.status !== "completed" || typeof part.messageID !== "string" || typeof part.callID !== "string") continue
    const call = JSON.stringify([part.messageID, part.callID])
    if (captured.has(call) || seen.has(call)) continue
    seen.add(call)
    const resultDigest = QuantCodeToolCatalog.digest(state)
    for (const [index, item] of candidates(state).entries()) {
      const key = QuantCodeToolCatalog.digest([row.id, index])
      const common = { id: `artifact_${key}`, name: item.name, mime: item.mime, kind: item.kind, source: item.source,
        source_event_id: row.id, source_event_seq: row.seq, message_id: part.messageID, call_id: part.callID, result_digest: resultDigest }
      if (item.data && !item.invalid && (item.sha256 === undefined || item.sha256 === hash(item.data)) &&
        (item.bytes === undefined || item.bytes === item.data.byteLength)) {
        const sha256 = hash(item.data)
        inline.set(common.id, item.data)
        artifacts.push({ ...common, bytes: item.data.byteLength, sha256, ref: `snapshot:${sha256}`, capture_status: "available" })
      } else artifacts.push({ ...common, ref: `unavailable:${key}`, capture_status: "unavailable", unavailable_reason: "original_not_captured" })
    }
  }
  artifacts.sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
  if (new Set(artifacts.map(item => item.id)).size !== artifacts.length) throw new Error("产物事件含重复标识。")
  return { artifacts, inline }
})

export async function content(artifact: QuantCodeTaskIndex.ArtifactRef, inline: ReadonlyMap<string, Buffer>, offset: number) {
  if (!Number.isSafeInteger(offset) || offset < 0 || offset % CHUNK_BYTES !== 0) throw new Error("产物分块位置无效。")
  if (artifact.capture_status !== "available") return { delivery_status: "unavailable" as const, next_offset: null }
  if (artifact.bytes === undefined || !artifact.sha256 || offset > artifact.bytes || (offset === artifact.bytes && offset !== 0))
    throw new Error("产物内容长度或分块位置无效。")
  const saved = inline.get(artifact.id)
  const chunk = saved ? saved.subarray(offset, Math.min(offset + CHUNK_BYTES, saved.byteLength)) : await (async () => {
    const filename = path.join(directory, artifact.sha256!)
    const canonical = await realpath(filename)
    if (path.dirname(canonical) !== await realpath(directory)) throw new Error("invalid artifact object")
    const file = await open(filename, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0))
    try {
      const before = await file.stat()
      if (!before.isFile() || before.size !== artifact.bytes || before.nlink !== 1 || (process.platform !== "win32" &&
        ((before.mode & 0o077) || (process.getuid && before.uid !== process.getuid())))) throw new Error("invalid artifact object")
      const data = Buffer.alloc(Math.min(CHUNK_BYTES, before.size - offset))
      const read = await file.read(data, 0, data.length, offset)
      const after = await file.stat()
      const linked = await lstat(filename)
      if (read.bytesRead !== data.length || before.ino !== linked.ino || before.dev !== linked.dev || linked.isSymbolicLink() ||
        before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs || before.size !== after.size ||
        linked.size !== after.size || linked.mtimeMs !== after.mtimeMs || await realpath(filename) !== canonical)
        throw new Error("artifact changed during read")
      return data
    } finally { await file.close() }
  })().catch(() => undefined)
  if (!chunk) return { delivery_status: "unavailable" as const, next_offset: null }
  return { delivery_status: "available" as const, content: chunk.toString("base64"), encoding: "base64" as const,
    chunk_sha256: hash(chunk), next_offset: offset + chunk.byteLength < artifact.bytes ? offset + chunk.byteLength : null }
}

export * as QuantCodeArtifacts from "./artifacts"
