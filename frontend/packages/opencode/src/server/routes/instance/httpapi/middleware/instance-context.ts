import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeWorkspace } from "@/quantcode/workspace"
import { InstanceRef, WorkspaceRef } from "@/effect/instance-ref"
import { InstanceStore } from "@/project/instance-store"
import { Effect, Layer } from "effect"
import { HttpServerRequest, HttpServerResponse } from "effect/unstable/http"
import { HttpApiMiddleware } from "effect/unstable/httpapi"
import { WorkspaceRouteContext } from "./workspace-routing"
import { Global } from "@opencode-ai/core/global"
import { ProjectV2 } from "@opencode-ai/core/project"

export class InstanceContextMiddleware extends HttpApiMiddleware.Service<
  InstanceContextMiddleware,
  {
    requires: WorkspaceRouteContext
  }
>()("@opencode/ExperimentalHttpApiInstanceContext") {}

function decode(input: string): string {
  try {
    return decodeURIComponent(input)
  } catch {
    return input
  }
}

function provideInstanceContext<E>(
  effect: Effect.Effect<HttpServerResponse.HttpServerResponse, E>,
  store: InstanceStore.Interface,
): Effect.Effect<HttpServerResponse.HttpServerResponse, E, WorkspaceRouteContext | HttpServerRequest.HttpServerRequest> {
  return Effect.gen(function* () {
    const route = yield* WorkspaceRouteContext
    const directory = decode(route.directory)
    if (QuantCodeIdentity.enabled()) {
      const request = yield* HttpServerRequest.HttpServerRequest
      const pathname = new URL(request.url, "http://localhost").pathname
      // Identity/model/organization controls do not need to discover a user
      // repository. They must also work before a checkout has been enrolled.
      const hostRoute = /^\/(?:config|provider)(?:\/|$)/.test(pathname) || pathname === "/experimental/capabilities" ||
        /^\/experimental\/quantcode\/session\/[^/]+\/(?:task-index|artifacts(?:\/[^/]+)?)$/.test(pathname) ||
        (request.method === "GET" && /^\/experimental\/quantcode\/session\/[^/]+\/(?:write-receipts|execution-lock|budget\/review)$/.test(pathname)) ||
        (request.method === "POST" && /^\/experimental\/quantcode\/session\/[^/]+\/(?:write-receipts\/review|execution-lock\/recover|budget\/(?:review|lock\/recover))$/.test(pathname)) ||
        pathname === "/experimental/proxy/models" || (request.method === "GET" && (pathname === "/project" || /^\/project\/[^/]+\/directories$/.test(pathname))) ||
        (pathname.startsWith("/experimental/quantcode/") && !pathname.startsWith("/experimental/quantcode/session/"))
      if (hostRoute) {
        const ctx = { directory: Global.Path.config, worktree: Global.Path.config,
          project: { id: ProjectV2.ID.global, worktree: Global.Path.config, time: { created: 0, updated: 0 }, sandboxes: [] } }
        return yield* effect.pipe(Effect.provideService(InstanceRef, ctx), Effect.provideService(WorkspaceRef, undefined))
      }
      // Every remaining instance route validates before project resolution,
      // hooks, Git discovery or background bootstrap can observe this path.
      const grant = yield* Effect.promise(() => QuantCodeWorkspace.authorize(directory))
      const ctx = yield* store.load({ directory: grant.directory })
      yield* Effect.promise(() => QuantCodeWorkspace.revalidate(grant))
      return yield* effect.pipe(Effect.provideService(InstanceRef, ctx), Effect.provideService(WorkspaceRef, route.workspaceID))
    }
    const ctx = yield* store.load({ directory })
    return yield* effect.pipe(
      Effect.provideService(InstanceRef, ctx),
      Effect.provideService(WorkspaceRef, route.workspaceID),
    )
  })
}

export const instanceContextLayer = Layer.effect(
  InstanceContextMiddleware,
  Effect.gen(function* () {
    const store = yield* InstanceStore.Service
    return InstanceContextMiddleware.of((effect) => provideInstanceContext(effect, store))
  }),
)
