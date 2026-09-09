import { Effect } from "effect"
import { HttpRouter, HttpServerRequest, HttpServerResponse } from "effect/unstable/http"
import { QuantCodeIdentity } from "@/quantcode/identity"

/** The bundled server also exposes Core's independent V2 executor. QuantCode
 * currently uses SessionPrompt; enabling the migration must not leave the V2
 * executor, raw event stream or PTY routes as alternate ungoverned entrances.
 * This is product-wide routing policy, not per-resource authorization. */
export const quantcodeRuntimeLayer = HttpRouter.middleware<{ handles: unknown }>()((effect) =>
  Effect.gen(function* () {
    if (!QuantCodeIdentity.enabled()) return yield* effect
    const request = yield* HttpServerRequest.HttpServerRequest
    const path = new URL(request.url, "http://localhost").pathname
    if (path === "/api" || path.startsWith("/api/")) {
      return HttpServerResponse.jsonUnsafe({
        name: "QuantCodeRuntimeRouteUnavailable",
        message: "当前 QuantCode 使用统一任务接口，不开放另一套执行器接口。",
      }, { status: 409 })
    }
    return yield* effect
  }),
).layer
