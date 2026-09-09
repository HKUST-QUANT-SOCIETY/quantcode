import { LayerNode } from "@opencode-ai/core/effect/layer-node"
import path from "path"
import { Effect, Layer, Record, Result, Schema, Context } from "effect"
import { NonNegativeInt } from "@opencode-ai/core/schema"
import { Global } from "@opencode-ai/core/global"
import { FSUtil } from "@opencode-ai/core/fs-util"
import { lstat } from "node:fs/promises"
import { readPrivateFile } from "@/quantcode/private-file"
import { QuantCodeIdentity } from "@/quantcode/identity"
import { QuantCodeConfigPolicy } from "@/quantcode/config-policy"

export const OAUTH_DUMMY_KEY = "opencode-oauth-dummy-key"

const file = path.join(Global.Path.data, "auth.json")

const fail = (message: string) => (cause: unknown) => new AuthError({ message, cause })

export class Oauth extends Schema.Class<Oauth>("OAuth")({
  type: Schema.Literal("oauth"),
  refresh: Schema.String,
  access: Schema.String,
  expires: NonNegativeInt,
  accountId: Schema.optional(Schema.String),
  enterpriseUrl: Schema.optional(Schema.String),
}) {}

export class Api extends Schema.Class<Api>("ApiAuth")({
  type: Schema.Literal("api"),
  key: Schema.String,
  metadata: Schema.optional(Schema.Record(Schema.String, Schema.String)),
}) {}

export class WellKnown extends Schema.Class<WellKnown>("WellKnownAuth")({
  type: Schema.Literal("wellknown"),
  key: Schema.String,
  token: Schema.String,
}) {}

export const Info = Schema.Union([Oauth, Api, WellKnown]).annotate({ discriminator: "type", identifier: "Auth" })
export type Info = Schema.Schema.Type<typeof Info>

export class AuthError extends Schema.TaggedErrorClass<AuthError>()("AuthError", {
  message: Schema.String,
  cause: Schema.optional(Schema.Defect()),
}) {}

export interface Interface {
  readonly get: (providerID: string) => Effect.Effect<Info | undefined, AuthError>
  readonly all: () => Effect.Effect<Record<string, Info>, AuthError>
  readonly set: (key: string, info: Info) => Effect.Effect<void, AuthError>
  readonly remove: (key: string) => Effect.Effect<void, AuthError>
}

export class Service extends Context.Service<Service, Interface>()("@opencode/Auth") {}

const layer = Layer.effect(
  Service,
  Effect.gen(function* () {
    const fsys = yield* FSUtil.Service
    const decode = Schema.decodeUnknownOption(Info)

    const all = Effect.fn("Auth.all")(function* () {
      if (QuantCodeIdentity.enabled()) {
        const data = yield* Effect.tryPromise({
          try: async () => {
            const exists = await lstat(file).catch(error => {
              if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined
              throw error
            })
            if (!exists) return {}
            const value: unknown = JSON.parse(await readPrivateFile(file, 262144))
            if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid auth file")
            return value as Record<string, unknown>
          }, catch: () => new AuthError({ message: "无法读取 QuantCode 私有模型凭据。" }),
        })
        return Record.filterMap(data, value => Result.fromOption(decode(value), () => undefined))
      }
      if (process.env.OPENCODE_AUTH_CONTENT) {
        try {
          return JSON.parse(process.env.OPENCODE_AUTH_CONTENT)
        } catch (err) {}
      }

      const data = (yield* fsys.readJson(file).pipe(Effect.orElseSucceed(() => ({})))) as Record<string, unknown>
      return Record.filterMap(data, (value) => Result.fromOption(decode(value), () => undefined))
    })

    const get = Effect.fn("Auth.get")(function* (providerID: string) {
      return (yield* all())[providerID]
    })

    const set = Effect.fn("Auth.set")(function* (key: string, info: Info) {
      if (QuantCodeIdentity.enabled()) {
        yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
        if (!QuantCodeConfigPolicy.validProviderID(key) || info.type !== "api" || !info.key.trim() ||
            /\{(?:env|file):|\$\{/i.test(info.key) || info.key.length > 16384 ||
            !QuantCodeConfigPolicy.credentialMatches(info, info.metadata?.quantcode_base_url)) {
          return yield* new AuthError({ message: "QuantCode 的 API Key 必须绑定到对应的自定义接口 URL。" })
        }
      }
      const norm = key.replace(/\/+$/, "")
      const data = yield* all()
      if (norm !== key) delete data[key]
      delete data[norm + "/"]
      yield* fsys
        .writeJson(file, { ...data, [norm]: info }, 0o600)
        .pipe(Effect.mapError(fail("Failed to write auth data")))
    })

    const remove = Effect.fn("Auth.remove")(function* (key: string) {
      if (QuantCodeIdentity.enabled()) yield* Effect.promise(() => QuantCodeIdentity.currentIdentity())
      const norm = key.replace(/\/+$/, "")
      const data = yield* all()
      delete data[key]
      delete data[norm]
      yield* fsys.writeJson(file, data, 0o600).pipe(Effect.mapError(fail("Failed to write auth data")))
    })

    return Service.of({ get, all, set, remove })
  }),
)

export const node = LayerNode.make({ service: Service, layer: layer, deps: [FSUtil.node] })

export * as Auth from "."
