import { QuantCodeAccess } from "@/quantcode/access"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { Question } from "@/question"
import { QuestionID } from "@/question/schema"
import { Effect } from "effect"
import { HttpApiBuilder } from "effect/unstable/httpapi"
import { InstanceHttpApi } from "../api"
import { QuestionNotFoundError } from "../errors"

export const questionHandlers = HttpApiBuilder.group(InstanceHttpApi, "question", (handlers) =>
  Effect.gen(function* () {
    const svc = yield* Question.Service

    const list = Effect.fn("QuestionHttpApi.list")(function* () {
      const pending = yield* svc.list()
      const visible = yield* QuantCodeAccess.visibleSessions(pending.map(item => item.sessionID))
      return pending.filter(item => visible.has(item.sessionID))
    })

    const reply = Effect.fn("QuestionHttpApi.reply")(function* (ctx: {
      params: { requestID: QuestionID }
      payload: Question.Reply
    }) {
      if (QuantCodeIdentity.enabled()) {
        const pending = (yield* svc.list()).find(item => item.id === ctx.params.requestID)
        if (!pending) return yield* new QuestionNotFoundError({ requestID: String(ctx.params.requestID), message: "请求不存在或已处理。" })
        yield* QuantCodeAccess.requireSession(pending.sessionID)
      }
      yield* svc
        .reply({
          requestID: ctx.params.requestID,
          answers: ctx.payload.answers,
        })
        .pipe(
          Effect.catchTag("Question.NotFoundError", (error) =>
            Effect.fail(
              new QuestionNotFoundError({
                requestID: String(error.requestID),
                message: `Question request not found: ${error.requestID}`,
              }),
            ),
          ),
        )
      return true
    })

    const reject = Effect.fn("QuestionHttpApi.reject")(function* (ctx: { params: { requestID: QuestionID } }) {
      if (QuantCodeIdentity.enabled()) {
        const pending = (yield* svc.list()).find(item => item.id === ctx.params.requestID)
        if (!pending) return yield* new QuestionNotFoundError({ requestID: String(ctx.params.requestID), message: "请求不存在或已处理。" })
        yield* QuantCodeAccess.requireSession(pending.sessionID)
      }
      yield* svc.reject(ctx.params.requestID).pipe(
        Effect.catchTag("Question.NotFoundError", (error) =>
          Effect.fail(
            new QuestionNotFoundError({
              requestID: String(error.requestID),
              message: `Question request not found: ${error.requestID}`,
            }),
          ),
        ),
      )
      return true
    })

    return handlers.handle("list", list).handle("reply", reply).handle("reject", reject)
  }),
)
