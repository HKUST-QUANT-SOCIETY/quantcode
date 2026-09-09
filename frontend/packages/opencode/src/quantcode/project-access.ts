import path from "node:path"
import { Effect, Layer } from "effect"
import { ChildProcess } from "effect/unstable/process"
import { AppProcess } from "@opencode-ai/core/process"
import { FSUtil } from "@opencode-ai/core/fs-util"
import { Git } from "@opencode-ai/core/git"
import { ProjectV2 } from "@opencode-ai/core/project"
import { ProjectDirectories } from "@opencode-ai/core/project/directories"
import { AbsolutePath } from "@opencode-ai/core/schema"
import { Hash } from "@opencode-ai/core/util/hash"
import type { Project } from "@opencode-ai/schema/project"
import { QuantCodeWorkspace, type WorkspaceGrant } from "./workspace"
import { QuantCodeIdentity, type Identity } from "./identity"
import { QuantCodeGitAccess } from "./git-access"

/** Use the existing Core repository resolver with bounded filesystem and
 * process services; the .git/opencode compatibility cache is not authority. */
export const resolve = Effect.fn("QuantCodeProjectAccess.resolve")(function* (grant: WorkspaceGrant): Effect.fn.Return<ProjectV2.Resolved, never, FSUtil.Service | AppProcess.Service | ProjectDirectories.Service> {
  const fs = yield* FSUtil.Service
  const processes = yield* AppProcess.Service
  const directories = yield* ProjectDirectories.Service
  const controlledFs = { ...fs,
    up: (input: Parameters<FSUtil.Interface["up"]>[0]) => Effect.gen(function* () {
      const start = yield* Effect.promise(() => QuantCodeWorkspace.target(grant, input.start))
      return yield* fs.up({ ...input, start, stop: grant.root })
    }),
    readFileString: (file: string) => Effect.promise(async () => {
      if (path.basename(file) === "opencode") return "" // never migrate sessions from a repository-authored ID
      return (await QuantCodeWorkspace.readFile(grant, file)).content.toString("utf8")
    }),
  } satisfies FSUtil.Interface
  const controlled = { ...processes,
    run: (command: ChildProcess.Command, options?: AppProcess.RunOptions) => Effect.scoped(Effect.gen(function* () {
      if (command._tag !== "StandardCommand") throw new Error("项目发现不接受复合宿主命令。")
      const launch = yield* Effect.acquireRelease(
        Effect.promise(() => QuantCodeGitAccess.prepareRead(command.options.cwd ?? grant.directory, command.args)),
        value => Effect.promise(() => value.sandbox.dispose()),
      )
      if (launch.grant.identity.session_id !== grant.identity.session_id) throw new QuantCodeIdentity.IdentityError()
      const result = yield* processes.run(ChildProcess.make(launch.sandbox.command, launch.sandbox.args, {
        cwd: launch.sandbox.cwd, env: launch.sandbox.env, extendEnv: false, stdin: "ignore", forceKillAfter: "3 seconds",
      }), { ...options, timeout: "20 seconds", maxOutputBytes: 4_000_000, maxErrorBytes: 0 })
      yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
      return { ...result, stdout: QuantCodeGitAccess.publicOutput(command.args, result.stdout) }
    })),
  } satisfies AppProcess.Interface
  const gitLayer = Git.layer.pipe(Layer.provide(Layer.succeed(FSUtil.Service, controlledFs)), Layer.provide(Layer.succeed(AppProcess.Service, controlled)))
  const layer = ProjectV2.layer.pipe(Layer.provide(gitLayer), Layer.provide(Layer.succeed(FSUtil.Service, controlledFs)),
    Layer.provide(Layer.succeed(ProjectDirectories.Service, directories)))
  const result = yield* ProjectV2.Service.use(project => project.resolve(AbsolutePath.make(grant.directory))).pipe(Effect.provide(layer))
  if (result.vcs) {
    yield* Effect.promise(() => QuantCodeWorkspace.target(grant, result.directory))
    yield* Effect.promise(() => QuantCodeWorkspace.target(grant, result.vcs!.store))
    return result.id === ProjectV2.ID.global ? { ...result, id: ProjectV2.ID.make(Hash.fast(`quantcode-workspace:${result.directory}`)) } : result
  }
  return { id: ProjectV2.ID.make(Hash.fast(`quantcode-workspace:${grant.root}`)), directory: AbsolutePath.make(grant.root) }
})

export async function visible<T extends Project.Info>(project: T, identity: Identity): Promise<T | undefined> {
  const entries = await Promise.all([project.worktree, ...project.sandboxes].map(directory =>
    QuantCodeWorkspace.authorize(directory, "read", identity).catch(() => undefined)))
  const granted = entries.filter((item): item is WorkspaceGrant => !!item)
  if (!granted.length) return
  for (const grant of granted) await QuantCodeWorkspace.revalidate(grant)
  return { ...project, worktree: granted[0].directory, sandboxes: granted.slice(1).map(grant => grant.directory), commands: undefined }
}

export * as QuantCodeProjectAccess from "./project-access"
