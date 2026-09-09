import { QuantCodeAccess } from "@/quantcode/access"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { PermissionV1 } from "@opencode-ai/core/v1/permission"
import { Permission } from "@/permission"
import { Effect } from "effect"
import { HttpApiBuilder } from "effect/unstable/httpapi"
import { InstanceHttpApi } from "../api"
import { PermissionNotFoundError } from "../errors"

export const permissionHandlers = HttpApiBuilder.group(InstanceHttpApi, "permission", (handlers) =>
  Effect.gen(function* () {
    const svc = yield* Permission.Service

    const list = Effect.fn("PermissionHttpApi.list")(function* () {
      const pending = yield* svc.list()
      const visible = yield* QuantCodeAccess.visibleSessions(pending.map(item => item.sessionID))
      return pending.filter(item => visible.has(item.sessionID))
    })

    const reply = Effect.fn("PermissionHttpApi.reply")(function* (ctx: {
      params: { requestID: PermissionV1.ID }
      payload: PermissionV1.ReplyBody
    }) {
      if (QuantCodeIdentity.enabled()) {
        const pending = (yield* svc.list()).find(item => item.id === ctx.params.requestID)
        if (!pending) return yield* new PermissionNotFoundError({ requestID: String(ctx.params.requestID), message: "请求不存在或已处理。" })
        yield* QuantCodeAccess.requireSession(pending.sessionID)
      }
      yield* svc
        .reply({
          requestID: ctx.params.requestID,
          reply: ctx.payload.reply,
          message: ctx.payload.message,
          expected_digest: ctx.payload.expected_digest,
        })
        .pipe(
          Effect.catchTag("Permission.NotFoundError", (error) =>
            Effect.fail(
              new PermissionNotFoundError({
                requestID: String(error.requestID),
                message: `Permission request not found: ${error.requestID}`,
              }),
            ),
          ),
        )
      return true
    })

    return handlers.handle("list", list).handle("reply", reply)
  }),
)
