import * as InstanceState from "@/effect/instance-state"
import { Project } from "@/project/project"
import { ProjectV2 } from "@opencode-ai/core/project"
import { Effect } from "effect"
import { HttpApiBuilder } from "effect/unstable/httpapi"
import { InstanceHttpApi } from "../api"
import { ProjectNotFoundError } from "../errors"
import { markInstanceForReload } from "../lifecycle"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeWorkspace } from "@/quantcode/workspace"

export const projectHandlers = HttpApiBuilder.group(InstanceHttpApi, "project", (handlers) =>
  Effect.gen(function* () {
    const svc = yield* Project.Service
    const project = yield* ProjectV2.Service

    const list = Effect.fn("ProjectHttpApi.list")(function* () {
      return yield* svc.list()
    })

    const current = Effect.fn("ProjectHttpApi.current")(function* () {
      const context = yield* InstanceState.context
      if (!QuantCodeIdentity.enabled()) return context.project
      const current = yield* svc.get(context.project.id)
      if (!current) throw new QuantCodeWorkspace.WorkspaceDenied()
      return current
    })

    const initGit = Effect.fn("ProjectHttpApi.initGit")(function* () {
      const ctx = yield* InstanceState.context
      const next = yield* svc.initGit({ directory: ctx.directory, project: ctx.project })
      if (next.id === ctx.project.id && next.vcs === ctx.project.vcs && next.worktree === ctx.project.worktree)
        return next
      yield* markInstanceForReload(ctx, {
        directory: ctx.directory,
        worktree: ctx.directory,
        project: next,
      })
      return next
    })

    const update = Effect.fn("ProjectHttpApi.update")(function* (ctx: {
      params: { projectID: ProjectV2.ID }
      payload: Project.UpdatePayload
    }) {
      return yield* svc.update({ ...ctx.payload, projectID: ctx.params.projectID }).pipe(
        Effect.catchTag("Project.NotFoundError", (error) =>
          Effect.fail(
            new ProjectNotFoundError({
              projectID: error.projectID,
              message: `Project not found: ${error.projectID}`,
            }),
          ),
        ),
      )
    })

    const directories = Effect.fn("ProjectHttpApi.directories")(function* (ctx: { params: { projectID: ProjectV2.ID } }) {
      if (!QuantCodeIdentity.enabled()) return yield* project.directories({ projectID: ctx.params.projectID })
      if (!(yield* svc.get(ctx.params.projectID))) return []
      const identity = yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
      const entries = yield* project.directories({ projectID: ctx.params.projectID })
      const visible = yield* Effect.forEach(entries, entry => Effect.promise(async () => {
        const grant = await QuantCodeWorkspace.authorize(entry.directory, "read", identity).catch(() => undefined)
        if (!grant) return undefined
        await QuantCodeWorkspace.revalidate(grant)
        return entry
      }))
      return visible.filter(entry => entry !== undefined)
    })

    return handlers
      .handle("list", list)
      .handle("current", current)
      .handle("initGit", initGit)
      .handle("update", update)
      .handle("directories", directories)
  }),
)
