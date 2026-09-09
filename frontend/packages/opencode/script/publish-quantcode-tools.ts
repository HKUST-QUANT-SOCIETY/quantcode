/** Host-maintainer CLI; never registered as a model tool or HTTP endpoint.
 * prepare binds explicitly reviewed effects to the real exported wire schema
 * and a private snapshot of one effective MCP server config. It only creates a
 * candidate file. publish/rollback are separate compare-and-swap operations.
 *
 * bun script/publish-quantcode-tools.ts status
 * bun script/publish-quantcode-tools.ts prepare REVIEW SCHEMAS SERVER CONFIG OUTPUT RELEASE
 * bun script/publish-quantcode-tools.ts publish /absolute/reviewed.json EXPECTED_DIGEST
 * bun script/publish-quantcode-tools.ts rollback ARCHIVED_DIGEST EXPECTED_DIGEST
 * Use absent for a first publication. Store the entire control directory
 * outside research workspaces; it contains private locks and release history.
 */
import { readFile, realpath } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { z } from "zod"
import { Global } from "@opencode-ai/core/global"
import { QuantCodeToolCatalog } from "../src/quantcode/tool-catalog"
import { readPrivateFile } from "../src/quantcode/private-file"
import { digest, readCurrent, privateDirectory, writeNewPrivateFile, updateHostFile } from "./quantcode-host-file"

const [mode, ...args] = process.argv.slice(2)
if (process.env.OPENCODE_CHANNEL !== "quantcode") throw new Error("Run this host CLI with OPENCODE_CHANNEL=quantcode")
const destination = process.env.QUANTCODE_TOOL_CATALOG_FILE ?? path.join(Global.Path.config, "tool-catalog.json")

function json(content: string) {
  try { return JSON.parse(content) as unknown } catch { throw new Error("Invalid JSON in host-maintainer input") }
}

function release(input: unknown) {
  const parsed = QuantCodeToolCatalog.releaseSchema.safeParse(input)
  if (!parsed.success) throw new Error("Invalid reviewed tool release")
  const keys = parsed.data.tools.map(entry => JSON.stringify([entry.server, entry.tool]))
  if (new Set(keys).size !== keys.length) throw new Error("Duplicate tool declarations")
  if (parsed.data.tools.some(entry => entry.purpose !== "ordinary" && entry.effect !== "read")) throw new Error("Inspection evidence requires a reviewed read-only tool")
  if (parsed.data.tools.some(entry => entry.effect === "personal_write" && !entry.path_arguments.length)) throw new Error("Write tools require reviewed file parameter paths")
  if (parsed.data.tools.some(entry => entry.effect === "shared_write" && entry.status === "published" && !entry.resource)) throw new Error("Shared writes require reviewed resource and version parameters")
  for (const entry of parsed.data.tools) if (entry.resource) new RegExp(entry.resource.key_pattern)
  return parsed.data
}

if (mode === "prepare") {
  const [reviewFile, schemasFile, server, configFile, output, name] = args
  if (args.length !== 6 || !server || !name || ![reviewFile, schemasFile, configFile, output].every(item => path.isAbsolute(item ?? ""))) {
    throw new Error("Usage: prepare ABSOLUTE_REVIEW ABSOLUTE_SCHEMAS SERVER ABSOLUTE_PRIVATE_CONFIG ABSOLUTE_OUTPUT RELEASE")
  }
  const reviewedText = await readFile(reviewFile, "utf8")
  const parsed = z.object({
    version: z.literal(1), id: z.string().min(1),
    reviewed_sources: z.record(z.string(), z.string().regex(/^[a-f0-9]{64}$/)),
    tools: z.array(QuantCodeToolCatalog.entrySchema.omit({ server: true, server_config_hash: true, input_schema_hash: true }).extend({
      source: z.object({ file: z.string().min(1), symbol: z.string().min(1) }).strict(),
      review: z.string().min(1),
    }).strict()).min(1),
  }).strict().safeParse(json(reviewedText))
  if (!parsed.success) throw new Error("Invalid effect review; declarations must be explicit")
  const review = parsed.data
  const repository = await realpath(fileURLToPath(new URL("../../../../", import.meta.url)))
  for (const [relative, expected] of Object.entries(review.reviewed_sources)) {
    if (path.isAbsolute(relative) || relative.includes("\\") || relative.split("/").some(part => !part || part === "." || part === "..")) {
      throw new Error("Review source paths must remain inside the QuantCode source tree")
    }
    const actual = await realpath(path.join(repository, relative))
    if (!actual.startsWith(repository + path.sep) || digest(await readFile(actual, "utf8")) !== expected) {
      throw new Error(`Reviewed implementation changed: ${relative}; review its effects again before preparing a release`)
    }
  }
  if (review.tools.some(entry => !review.reviewed_sources[entry.source.file])) throw new Error("Every declaration needs a pinned implementation source")
  const exported = z.object({ version: z.literal(1), review_digest: z.string(),
    tools: z.array(z.object({ name: z.string(), inputSchema: z.record(z.string(), z.unknown()) }).passthrough()),
  }).strict().safeParse(json(await readPrivateFile(schemasFile, 2_000_000)))
  if (!exported.success || exported.data.review_digest !== digest(reviewedText)) throw new Error("Wire schema export does not match the reviewed implementation")
  const schemas = exported.data.tools
  if (new Set(schemas.map(tool => tool.name)).size !== schemas.length) throw new Error("Duplicate exported tool schemas")
  const config = json(await readPrivateFile(configFile, 2_000_000))
  if (!config || typeof config !== "object" || Array.isArray(config) || !("type" in config) ||
      (config.type !== "local" && config.type !== "remote")) throw new Error("Provide exactly one effective local/remote MCP server configuration")
  const candidate = release({ version: 1, release: `${review.id}@${digest(reviewedText).slice(0, 12)}:${name}`,
    published_at: new Date().toISOString(), tools: review.tools.map(entry => {
      const schema = schemas.find(tool => tool.name === entry.tool)
      if (!schema) throw new Error(`Missing actual wire schema for reviewed tool: ${entry.tool}`)
      const { source, review: rationale, ...policy } = entry
      return { ...policy, server, server_config_hash: QuantCodeToolCatalog.digest(config),
        input_schema_hash: QuantCodeToolCatalog.digest(schema.inputSchema) }
    }),
  })
  const content = JSON.stringify(candidate, null, 2) + "\n"
  await writeNewPrivateFile(output, content)
  process.stdout.write(JSON.stringify({ mode, release: candidate.release, digest: digest(content), tools: candidate.tools.length }) + "\n")
  process.exit(0)
}

if (!path.isAbsolute(destination)) throw new Error("Catalog destination must be absolute")
await privateDirectory(path.dirname(destination))
if (mode === "status" && args.length === 0) {
  const content = await readCurrent(destination, 2_000_000)
  const current = content === undefined ? undefined : release(json(content))
  process.stdout.write(JSON.stringify({ digest: content === undefined ? "absent" : digest(content), release: current?.release, tools: current?.tools.length ?? 0 }) + "\n")
  process.exit(0)
}
const [source, expected] = args
if (!["publish", "rollback"].includes(mode) || args.length !== 2 || !source || !/^(absent|[a-f0-9]{64})$/.test(expected ?? "")) {
  throw new Error("Usage: publish-quantcode-tools.ts status | prepare REVIEW SCHEMAS SERVER CONFIG OUTPUT RELEASE | publish|rollback SOURCE EXPECTED_DIGEST")
}
const input = mode === "rollback"
  ? await readPrivateFile(path.join(path.dirname(destination), "tool-catalog-history", `${/^[a-f0-9]{64}$/.test(source) ? source : (() => { throw new Error("Invalid archived digest") })()}.json`), 2_000_000)
  : await readPrivateFile(path.resolve(source), 2_000_000)
if (mode === "rollback" && digest(input) !== source) throw new Error("Archived release digest does not match its content")
const candidate = release(json(input))
const result = await updateHostFile({ filename: destination, expected, maxBytes: 2_000_000, history: "tool-catalog-history",
  update: async () => JSON.stringify(candidate, null, 2) + "\n",
})
// Only release metadata; never echo server configuration, headers or credentials.
process.stdout.write(JSON.stringify({ ...result, release: candidate.release, tools: candidate.tools.length, mode }) + "\n")
