import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import path from "path"
import { Effect, Layer, Context, Schema } from "effect"
import { NamedError } from "@opencode-ai/core/util/error"
import type { Agent } from "@/agent/agent"
import { EventV2Bridge } from "@/event-v2-bridge"
import { InstanceState } from "@/effect/instance-state"
import { Global } from "@opencode-ai/core/global"
import { SkillPlugin } from "@opencode-ai/core/plugin/skill"
import { Permission } from "@/permission"
import { FSUtil } from "@opencode-ai/core/fs-util"
import { Config } from "@/config/config"
import { FrontmatterError } from "@opencode-ai/core/v1/config/error"
import { ConfigMarkdown } from "@/config/markdown"
import { RuntimeFlags } from "@/effect/runtime-flags"
import { Glob } from "@opencode-ai/core/util/glob"
import { Discovery } from "./discovery"
import { isRecord } from "@/util/record"
import { escapeHtml } from "@/util/html"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeWorkspace } from "@/quantcode/workspace"
import { QuantCodeReadAccess } from "@/quantcode/read-access"
import { readHostFile } from "@/quantcode/private-file"
import { AppProcess } from "@opencode-ai/core/process"
import { parseOption } from "@opencode-ai/core/config/markdown"
import { lstat, readdir, realpath } from "node:fs/promises"

const CLAUDE_EXTERNAL_DIR = ".claude"
const AGENTS_EXTERNAL_DIR = ".agents"
const EXTERNAL_SKILL_PATTERN = "skills/**/SKILL.md"
const OPENCODE_SKILL_PATTERN = "{skill,skills}/**/SKILL.md"
const SKILL_PATTERN = "**/SKILL.md"

// Built-in skill that ships with opencode. The model's intuition for what an
// opencode.json should look like is often wrong, and opencode hard-fails on
// invalid config, so users hit cryptic startup errors. Loading this skill
// when the model is asked to touch opencode's own config files gives it the
// actual schemas instead of guesses.
const CUSTOMIZE_OPENCODE_SKILL_NAME = "customize-opencode"
const CUSTOMIZE_OPENCODE_SKILL_DESCRIPTION =
  "Use ONLY when the user is editing or creating opencode's own configuration: opencode.json, opencode.jsonc, files under .opencode/, or files under ~/.config/opencode/. Also use when creating or fixing opencode agents, subagents, skills, plugins, MCP servers, or permission rules. Do not use for the user's own application code, or for any project that is not configuring opencode itself."
const CUSTOMIZE_OPENCODE_SKILL_BODY = SkillPlugin.CustomizeOpencodeContent

export const Info = Schema.Struct({
  name: Schema.String,
  description: Schema.optional(Schema.String),
  location: Schema.String,
  content: Schema.String,
})
export type Info = Schema.Schema.Type<typeof Info>

const Issue = Schema.StructWithRest(
  Schema.Struct({
    message: Schema.String,
    path: Schema.Array(Schema.String),
  }),
  [Schema.Record(Schema.String, Schema.Unknown)],
)

function isSkillFrontmatter(data: unknown): data is { name: string; description?: string } {
  return (
    isRecord(data) &&
    typeof data.name === "string" &&
    (data.description === undefined || typeof data.description === "string")
  )
}

export class InvalidError extends Schema.TaggedErrorClass<InvalidError>()("SkillInvalidError", {
  path: Schema.String,
  message: Schema.optional(Schema.String),
  issues: Schema.optional(Schema.Array(Issue)),
}) {}

export class NameMismatchError extends Schema.TaggedErrorClass<NameMismatchError>()("SkillNameMismatchError", {
  path: Schema.String,
  expected: Schema.String,
  actual: Schema.String,
}) {}

export class NotFoundError extends Schema.TaggedErrorClass<NotFoundError>()("Skill.NotFoundError", {
  name: Schema.String,
  available: Schema.Array(Schema.String),
}) {
  override get message() {
    return `Skill "${this.name}" not found. Available skills: ${this.available.join(", ") || "none"}`
  }
}

type State = {
  skills: Record<string, Info>
  dirs: Set<string>
}

type DiscoveryState = {
  matches: string[]
  dirs: string[]
}

type ScanState = {
  matches: Set<string>
  dirs: Set<string>
}

export interface Interface {
  readonly get: (name: string) => Effect.Effect<Info | undefined>
  readonly require: (name: string) => Effect.Effect<Info, NotFoundError>
  readonly all: () => Effect.Effect<Info[]>
  readonly dirs: () => Effect.Effect<string[]>
  readonly available: (agent?: Agent.Info) => Effect.Effect<Info[]>
  readonly files: (name: string) => Effect.Effect<string[]>
  readonly readDocument: (name: string, file: string) => Effect.Effect<string>
}

const add = Effect.fnUntraced(function* (state: State, match: string, events: EventV2Bridge.Service["Service"]) {
  const md = yield* Effect.tryPromise({
    try: () => ConfigMarkdown.parse(match),
    catch: (err) => err,
  }).pipe(
    Effect.catch(
      Effect.fnUntraced(function* (err) {
        const message = FrontmatterError.isInstance(err) ? err.data.message : `Failed to parse skill ${match}`
        const { Session } = yield* Effect.promise(() => import("@/session/session"))
        yield* events.publish(Session.Event.Error, { error: new NamedError.Unknown({ message }).toObject() })
        yield* Effect.logError("failed to load skill", { skill: match, error: err })
        return undefined
      }),
    ),
  )

  if (!md) return

  if (!isSkillFrontmatter(md.data)) return

  if (state.skills[md.data.name]) {
    yield* Effect.logWarning("duplicate skill name", {
      name: md.data.name,
      existing: state.skills[md.data.name].location,
      duplicate: match,
    })
  }

  state.dirs.add(path.dirname(match))
  state.skills[md.data.name] = {
    name: md.data.name,
    description: md.data.description,
    location: match,
    content: md.content,
  }
})

const scan = Effect.fnUntraced(function* (
  state: ScanState,
  root: string,
  pattern: string,
  opts?: { dot?: boolean; scope?: string },
) {
  const matches = yield* Effect.tryPromise({
    try: () =>
      Glob.scan(pattern, {
        cwd: root,
        absolute: true,
        include: "file",
        symlink: true,
        dot: opts?.dot,
      }),
    catch: (error) => error,
  }).pipe(
    Effect.catch((error) => {
      if (!opts?.scope) return Effect.die(error)
      return Effect.logError(`failed to scan ${opts.scope} skills`, { dir: root, error: error }).pipe(
        Effect.as([] as string[]),
      )
    }),
  )

  for (const match of matches) {
    state.matches.add(match)
    state.dirs.add(path.dirname(match))
  }
})

const discoverSkills = Effect.fnUntraced(function* (
  config: Config.Interface,
  discovery: Discovery.Interface,
  fsys: FSUtil.Interface,
  global: Global.Interface,
  disableExternalSkills: boolean,
  disableClaudeCodeSkills: boolean,
  directory: string,
  worktree: string,
) {
  const state: ScanState = { matches: new Set(), dirs: new Set() }

  const externalDirs: string[] = []
  if (!disableExternalSkills) {
    if (!disableClaudeCodeSkills) externalDirs.push(CLAUDE_EXTERNAL_DIR)
    externalDirs.push(AGENTS_EXTERNAL_DIR)

    for (const dir of externalDirs) {
      const root = path.join(global.home, dir)
      if (!(yield* fsys.isDir(root))) continue
      yield* scan(state, root, EXTERNAL_SKILL_PATTERN, { dot: true, scope: "global" })
    }

    const upDirs = yield* fsys
      .up({ targets: externalDirs, start: directory, stop: worktree })
      .pipe(Effect.catch(() => Effect.succeed([] as string[])))

    for (const root of upDirs) {
      yield* scan(state, root, EXTERNAL_SKILL_PATTERN, { dot: true, scope: "project" })
    }
  }

  const configDirs = yield* config.directories()
  for (const dir of configDirs) {
    yield* scan(state, dir, OPENCODE_SKILL_PATTERN)
  }

  const cfg = yield* config.get()
  for (const item of cfg.skills?.paths ?? []) {
    const expanded = item.startsWith("~/") ? path.join(global.home, item.slice(2)) : item
    const dir = path.isAbsolute(expanded) ? expanded : path.join(directory, expanded)
    if (!(yield* fsys.isDir(dir))) {
      yield* Effect.logWarning("skill path not found", { path: dir })
      continue
    }

    yield* scan(state, dir, SKILL_PATTERN)
  }

  for (const url of cfg.skills?.urls ?? []) {
    const pulledDirs = yield* discovery.pull(url)
    for (const dir of pulledDirs) {
      yield* scan(state, dir, SKILL_PATTERN)
    }
  }

  return {
    matches: Array.from(state.matches),
    dirs: Array.from(state.dirs),
  }
})

const loadSkills = Effect.fnUntraced(function* (
  state: State,
  discovered: DiscoveryState,
  events: EventV2Bridge.Service["Service"],
) {
  yield* Effect.forEach(discovered.matches, (match) => add(state, match, events), {
    concurrency: "unbounded",
    discard: true,
  })

  yield* Effect.logInfo("init", { count: Object.keys(state.skills).length })
})

export class Service extends Context.Service<Service, Interface>()("@opencode/Skill") {}

const layer = Layer.effect(
  Service,
  Effect.gen(function* () {
    const discovery = yield* Discovery.Service
    const config = yield* Config.Service
    const events = yield* EventV2Bridge.Service
    const fsys = yield* FSUtil.Service
    const global = yield* Global.Service
    const flags = yield* RuntimeFlags.Service
    const processes = yield* AppProcess.Service

    const hostDocuments = async (root: string, target = root): Promise<string[]> => {
      const info = await lstat(target).catch(() => undefined)
      if (!info || info.isSymbolicLink()) return []
      const actual = await realpath(target)
      if (!QuantCodeWorkspace.contains(root, actual) || (process.platform !== "win32" &&
        ((info.mode & 0o022) || (process.getuid && info.uid !== process.getuid() && info.uid !== 0)))) return []
      if (info.isFile()) return actual.endsWith(".md") && info.nlink === 1 ? [actual] : []
      if (!info.isDirectory()) return []
      const result: string[] = []
      for (const name of await readdir(actual)) {
        result.push(...await hostDocuments(root, path.join(actual, name)))
        if (result.length > 1000) throw new Error("宿主 Skill 文档目录超过限制，请缩小发布范围。")
      }
      return result
    }

    const authorized = Effect.fn("Skill.authorized")(function* () {
      const directory = yield* InstanceState.directory
      const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(directory))
      const cfg = yield* config.getGlobal()
      const skills: Record<string, Info> = {}
      const host = new Set<string>()
      const trustedRoots = [path.join(global.config, "skills"), ...(process.env.QUANTCODE_BACKEND_ROOT
        ? [path.join(process.env.QUANTCODE_BACKEND_ROOT, ".opencode", "groups", grant.identity.group, "skills")] : [])]
      const roots: string[] = []
      for (const root of trustedRoots) {
        const info = yield* Effect.promise(() => lstat(root).catch(() => undefined))
        if (!info?.isDirectory() || info.isSymbolicLink()) continue
        const actual = yield* Effect.promise(() => realpath(root).catch(() => undefined))
        if (actual && !QuantCodeWorkspace.contains(grant.root, actual)) roots.push(actual)
      }
      const addText = (file: string, text: string, trusted: boolean) => {
        const md = parseOption(text)
        if (!md || !isSkillFrontmatter(md.data)) return
        if (skills[md.data.name]) throw new Error(`Skill 名称重复：${md.data.name}，请由维护员明确来源。`)
        skills[md.data.name] = { name: md.data.name, description: md.data.description, location: file, content: md.content }
        if (trusted) host.add(file)
      }
      for (const root of roots) {
        const files = yield* Effect.promise(() => hostDocuments(root))
        for (const file of files.filter(file => path.basename(file) === "SKILL.md")) {
          addText(file, yield* Effect.promise(() => readHostFile(file)), true)
        }
      }
      const workspaceRoots = new Set(["skills", "skill", ".agents/skills", ...(!flags.disableClaudeCodeSkills ? [".claude/skills"] : [])]
        .map(item => path.join(grant.directory, item)))
      for (const item of cfg.skills?.paths ?? []) {
        const expanded = item.startsWith("~/") ? path.join(global.home, item.slice(2)) : path.resolve(grant.directory, item)
        if (roots.some(root => QuantCodeWorkspace.contains(root, expanded))) continue
        workspaceRoots.add(yield* Effect.promise(() => QuantCodeWorkspace.target(grant, expanded)))
      }
      for (const root of workspaceRoots) {
        if (!(yield* Effect.promise(() => QuantCodeReadAccess.visible(grant, root)))) continue
        const files = yield* QuantCodeReadAccess.search(grant, processes,
          service => service.glob({ cwd: root, pattern: "**/SKILL.md", hidden: true, limit: 1000 })).pipe(Effect.orDie)
        for (const file of files) {
          const actual = path.resolve(root, file.path)
          if (!(yield* Effect.promise(() => QuantCodeReadAccess.visible(grant, actual)))) continue
          addText(actual, yield* Effect.promise(() => QuantCodeReadAccess.contextText(grant, actual)), false)
        }
      }
      yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
      return { grant, skills, host, roots }
    })
    const discovered = yield* InstanceState.make(
      Effect.fn("Skill.discovery")(function* (ctx) {
        return yield* discoverSkills(
          config,
          discovery,
          fsys,
          global,
          flags.disableExternalSkills,
          flags.disableClaudeCodeSkills,
          ctx.directory,
          ctx.worktree,
        )
      }),
    )
    const state = yield* InstanceState.make(
      Effect.fn("Skill.state")(function* () {
        const s: State = { skills: {}, dirs: new Set() }
        // Register the built-in skill BEFORE disk discovery so a user-disk
        // skill with the same name can override it.
        s.skills[CUSTOMIZE_OPENCODE_SKILL_NAME] = {
          name: CUSTOMIZE_OPENCODE_SKILL_NAME,
          description: CUSTOMIZE_OPENCODE_SKILL_DESCRIPTION,
          location: "<built-in>",
          content: CUSTOMIZE_OPENCODE_SKILL_BODY,
        }
        yield* loadSkills(s, yield* InstanceState.get(discovered), events)
        return s
      }),
    )

    const get = Effect.fn("Skill.get")(function* (name: string) {
      if (QuantCodeIdentity.enabled()) return (yield* authorized()).skills[name]
      const s = yield* InstanceState.get(state)
      return s.skills[name]
    })

    const require = Effect.fn("Skill.require")(function* (name: string) {
      if (QuantCodeIdentity.enabled()) {
        const selected = yield* authorized()
        if (selected.skills[name]) return selected.skills[name]
        return yield* new NotFoundError({ name, available: Object.keys(selected.skills).toSorted() })
      }
      const s = yield* InstanceState.get(state)
      const info = s.skills[name]
      if (info) return info
      return yield* new NotFoundError({ name, available: Object.keys(s.skills).toSorted() })
    })

    const all = Effect.fn("Skill.all")(function* () {
      if (QuantCodeIdentity.enabled()) return Object.values((yield* authorized()).skills)
      const s = yield* InstanceState.get(state)
      return Object.values(s.skills)
    })

    const dirs = Effect.fn("Skill.dirs")(function* () {
      if (QuantCodeIdentity.enabled()) {
        const selected = yield* authorized()
        // Host public Markdown is read through Skill, never a general file/Shell grant.
        return Object.values(selected.skills).filter(skill => !selected.host.has(skill.location)).map(skill => path.dirname(skill.location))
      }
      return (yield* InstanceState.get(discovered)).dirs
    })

    const available = Effect.fn("Skill.available")(function* (agent?: Agent.Info) {
      const s = QuantCodeIdentity.enabled() ? yield* authorized() : yield* InstanceState.get(state)
      const list = Object.values(s.skills).toSorted((a, b) => a.name.localeCompare(b.name))
      if (!agent) return list
      return list.filter((skill) => Permission.evaluate("skill", skill.name, agent.permission).action !== "deny")
    })

    const files = Effect.fn("Skill.files")(function* (name: string) {
      if (!QuantCodeIdentity.enabled()) return []
      const selected = yield* authorized()
      const info = selected.skills[name]
      if (!info) return []
      const directory = path.dirname(info.location)
      if (selected.host.has(info.location)) {
        const result = yield* Effect.promise(() => hostDocuments(directory))
        yield* Effect.promise(() => QuantCodeWorkspace.revalidate(selected.grant))
        return result.filter(file => file !== info.location).slice(0, 10)
      }
      const result = yield* QuantCodeReadAccess.search(selected.grant, processes,
        service => service.glob({ cwd: directory, pattern: "**/*.md", limit: 10 })).pipe(Effect.orDie)
      const visible = yield* Effect.forEach(result, file => Effect.promise(async () => {
        const target = path.resolve(directory, file.path)
        return target !== info.location && await QuantCodeReadAccess.visible(selected.grant, target) ? target : undefined
      }))
      yield* Effect.promise(() => QuantCodeWorkspace.revalidate(selected.grant))
      return visible.filter(file => file !== undefined)
    })
    const readDocument = Effect.fn("Skill.readDocument")(function* (name: string, file: string) {
      if (!QuantCodeIdentity.enabled()) throw new Error("此入口仅用于组织 Skill 文档。")
      const selected = yield* authorized()
      const info = selected.skills[name]
      if (!info) throw new Error("当前身份无法访问该 Skill。")
      const directory = path.dirname(info.location)
      const target = path.resolve(directory, file)
      if (!QuantCodeWorkspace.contains(directory, target) || !target.endsWith(".md")) throw new Error("仅可读取该 Skill 内的 Markdown 文档。")
      const text = selected.host.has(info.location) ? yield* Effect.promise(async () => {
        const actual = await realpath(target)
        if (!QuantCodeWorkspace.contains(directory, actual)) throw new Error("Skill 文档路径越界。")
        return readHostFile(actual)
      }) : yield* Effect.promise(() => QuantCodeReadAccess.contextText(selected.grant, target))
      yield* Effect.promise(() => QuantCodeWorkspace.revalidate(selected.grant))
      return text
    })
    return Service.of({ get, require, all, dirs, available, files, readDocument })
  }),
)

export function fmt(list: Info[], opts: { verbose: boolean }) {
  const described = list.filter((skill) => skill.description !== undefined)
  if (described.length === 0) return "No skills are currently available."
  if (opts.verbose) {
    return [
      "<available_skills>",
      ...described
        .toSorted((a, b) => a.name.localeCompare(b.name))
        .flatMap((skill) => [
          "  <skill>",
          `    <name>${escapeHtml(skill.name)}</name>`,
          `    <description>${escapeHtml(skill.description ?? "")}</description>`,
          `    <location>${escapeHtml(skill.location)}</location>`,
          "  </skill>",
        ]),
      "</available_skills>",
    ].join("\n")
  }

  return [
    "## Available Skills",
    ...described
      .toSorted((a, b) => a.name.localeCompare(b.name))
      .map((skill) => `- **${skill.name}**: ${skill.description}`),
  ].join("\n")
}

export const node = LayerNode.make({
  service: Service,
  layer: layer,
  deps: [Discovery.node, Config.node, EventV2Bridge.node, FSUtil.node, Global.node, RuntimeFlags.node, AppProcess.node],
})

export * as Skill from "."
