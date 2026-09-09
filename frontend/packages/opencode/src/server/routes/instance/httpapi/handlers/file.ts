import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeWorkspace, type WorkspaceGrant } from "@/quantcode/workspace"
import { QuantCodeReadAccess } from "@/quantcode/read-access"
import { AppProcess } from "@opencode-ai/core/process"
import * as InstanceState from "@/effect/instance-state"
import { FileSystem } from "@opencode-ai/core/filesystem"
import { LocationServiceMap, locationServiceMapLayer } from "@opencode-ai/core/location-services"
import { Ripgrep } from "@opencode-ai/core/ripgrep"
import { FSUtil } from "@opencode-ai/core/fs-util"
import { Location } from "@opencode-ai/core/location"
import { AbsolutePath, RelativePath } from "@opencode-ai/core/schema"
import { Effect, Layer, Option } from "effect"
import ignore from "ignore"
import path from "path"
import { HttpApiBuilder } from "effect/unstable/httpapi"
import { InstanceHttpApi } from "../api"

export const fileHandlers = HttpApiBuilder.group(InstanceHttpApi, "file", (handlers) =>
  Effect.gen(function* () {
    const ripgrep = yield* Ripgrep.Service
    const appProcess = yield* AppProcess.Service
    const locations = yield* LocationServiceMap.Service

    const authorize = Effect.fn("FileHttpApi.authorize")(function* (requested?: string) {
      if (!QuantCodeIdentity.enabled()) return
      const directory = (yield* InstanceState.context).directory
      const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(directory))
      if (requested !== undefined) yield* Effect.promise(() => QuantCodeWorkspace.target(grant, requested))
      return grant
    })
    const finish = (grant: WorkspaceGrant | undefined) => grant
      ? Effect.promise(() => QuantCodeWorkspace.revalidate(grant)).pipe(Effect.asVoid)
      : Effect.void

    const filesystem = Effect.fnUntraced(function* <A, E, R>(effect: Effect.Effect<A, E, R>) {
      return yield* effect.pipe(
        Effect.provide(
          locations.get(Location.Ref.make({ directory: AbsolutePath.make((yield* InstanceState.context).directory) })),
        ),
      )
    })

    const findText = Effect.fn("FileHttpApi.findText")(function* (ctx: { query: { pattern: string } }) {
      const grant = yield* authorize()
      const input = { cwd: (yield* InstanceState.context).directory, pattern: ctx.query.pattern, limit: 10 }
      const found = grant ? yield* QuantCodeReadAccess.search(grant, appProcess, service => service.grep(input)).pipe(Effect.orDie)
        : yield* ripgrep.grep(input).pipe(Effect.orDie)
      const admitted = grant ? (yield* Effect.forEach(found, match => Effect.promise(async () =>
        await QuantCodeReadAccess.visibleMatch(grant, input.cwd, match) ? match : undefined)))
          .filter(match => match !== undefined) : found
      const matches = admitted.map((match) => ({
        path: { text: match.entry.path },
        lines: { text: match.text },
        line_number: match.line,
        absolute_offset: match.offset,
        submatches: match.submatches.map((submatch) => ({
          match: { text: submatch.text },
          start: submatch.start,
          end: submatch.end,
        })),
      }))
      yield* finish(grant)
      return matches
    })

    const findFile = Effect.fn("FileHttpApi.findFile")(function* (ctx: {
      query: { query: string; dirs?: "true" | "false"; type?: "file" | "directory"; limit?: number }
    }) {
      const grant = yield* authorize()
      const directory = (yield* InstanceState.context).directory
      const limit = ctx.query.limit ?? 10
      const type = ctx.query.type ?? (ctx.query.dirs === "false" ? "file" : undefined)
      if (grant) return yield* QuantCodeReadAccess.find(grant, appProcess, { query: ctx.query.query, limit, type }).pipe(Effect.orDie)
      const started = performance.now()
      const found = yield* filesystem(FileSystem.Service.use((fs) => fs.find({ query: ctx.query.query, limit, type })))
      yield* Effect.logInfo("find file", {
        query: ctx.query.query,
        type,
        directory,
        limit,
        results: found.length,
        duration: Math.round(performance.now() - started),
      })
      return found.map(item => item.path)
    })

    const findSymbol = Effect.fn("FileHttpApi.findSymbol")(function* () {
      yield* authorize()
      return []
    })

    const list = Effect.fn("FileHttpApi.list")(function* (ctx: { query: { path: string } }) {
      const grant = yield* authorize(ctx.query.path)
      if (grant) {
        const entries = yield* QuantCodeReadAccess.list(grant, ctx.query.path, appProcess)
        const ignored = ignore()
        for (const filename of [".gitignore", ".ignore"]) {
          const content = yield* Effect.promise(() => QuantCodeWorkspace.readFile(grant, path.join(grant.root, filename))
            .then(file => file.content.toString("utf8"), () => ""))
          if (content) ignored.add(content)
        }
        const result = entries.map(entry => ({ ...entry,
          ignored: ignored.ignores(path.relative(grant.root, entry.absolute) + (entry.type === "directory" ? "/" : "")),
        }))
        yield* finish(grant)
        return result
      }
      const entries = yield* filesystem(
        Effect.gen(function* () {
          const fs = yield* FileSystem.Service
          const raw = yield* FSUtil.Service
          const location = yield* Location.Service
          const ignored = ignore()
          const gitignore = yield* raw
            .readFileString(path.join(location.project.directory, ".gitignore"))
            .pipe(Effect.catch(() => Effect.succeed("")))
          if (gitignore) ignored.add(gitignore)
          const ignorefile = yield* raw
            .readFileString(path.join(location.project.directory, ".ignore"))
            .pipe(Effect.catch(() => Effect.succeed("")))
          if (ignorefile) ignored.add(ignorefile)
          return (yield* fs.list({ path: RelativePath.make(ctx.query.path) })).map((item) => ({
            name: path.basename(item.path),
            path: item.path,
            absolute: path.resolve(location.directory, item.path),
            type: item.type,
            ignored: ignored.ignores(
              path.relative(location.project.directory, path.resolve(location.directory, item.path)) +
                (item.type === "directory" ? "/" : ""),
            ),
          }))
        }),
      )
      return entries
    })

    const content = Effect.fn("FileHttpApi.content")(function* (ctx: { query: { path: string } }) {
      const grant = yield* authorize(ctx.query.path)
      const directory = (yield* InstanceState.context).directory
      const file = path.resolve(directory, ctx.query.path)
      if (!FSUtil.contains(directory, file)) return yield* Effect.die(new Error("Path escapes the location"))
      if (!(yield* FSUtil.Service.use((fs) => fs.existsSafe(file)))) {
        yield* finish(grant)
        return { type: "text" as const, content: "" }
      }
      const read: Effect.Effect<{ content: Uint8Array; mime: string }> = grant
        ? Effect.promise(() => QuantCodeWorkspace.readFile(grant, ctx.query.path)).pipe(Effect.map(item => ({ content: item.content, mime: FSUtil.mimeType(item.path) })))
        : filesystem(FileSystem.Service.use((fs) => fs.read({ path: RelativePath.make(ctx.query.path) })))
      const result = yield* read.pipe(
        Effect.flatMap((item) =>
          Effect.gen(function* () {
            const text = item.content.includes(0)
              ? Option.none<string>()
              : yield* Effect.sync(() => new TextDecoder("utf-8", { fatal: true }).decode(item.content)).pipe(
                  Effect.option,
                )
            return { item, text }
          }),
        ),
        Effect.map(({ item, text }) =>
          Option.isSome(text)
            ? { type: "text" as const, content: text.value }
            : {
                type: "binary" as const,
                content: Buffer.from(item.content).toString("base64"),
                encoding: "base64" as const,
                mimeType: item.mime,
              },
        ),
      )
      if (grant) yield* Effect.promise(() => QuantCodeWorkspace.target(grant, ctx.query.path))
      yield* finish(grant)
      return result
    })

    const status = Effect.fn("FileHttpApi.status")(function* () {
      yield* authorize()
      return []
    })

    return handlers
      .handle("findText", findText)
      .handle("findFile", findFile)
      .handle("findSymbol", findSymbol)
      .handle("list", list)
      .handle("content", content)
      .handle("status", status)
  }),
).pipe(Layer.provide(locationServiceMapLayer))
