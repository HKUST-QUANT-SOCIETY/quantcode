export * as Database from "./database"

import { EffectDrizzleSqlite } from "@opencode-ai/effect-drizzle-sqlite"
import { layer as sqliteLayer } from "#sqlite"
import { Context, Effect, Layer } from "effect"
import { Global } from "../global"
import { Flag } from "../flag/flag"
import { isAbsolute, join } from "path"
import { DatabaseMigration } from "./migration"
import { InstallationChannel } from "../installation/version"
import { makeGlobalNode } from "../effect/app-node"

const makeDatabase = EffectDrizzleSqlite.makeWithDefaults()
type DatabaseShape = Effect.Success<typeof makeDatabase>

export interface Interface {
  db: DatabaseShape
}

export class Service extends Context.Service<Service, Interface>()("@opencode/v2/storage/Database") {}

export const layer = Layer.effect(
  Service,
  Effect.gen(function* () {
    const db = yield* makeDatabase

    yield* db.run("PRAGMA journal_mode = WAL")
    // QuantCode records write admission before external effects in this same
    // event log. WAL NORMAL can lose that admission on power failure.
    yield* db.run(process.env.OPENCODE_CHANNEL === "quantcode" && process.env.QUANTCODE_UNIFIED_RUNTIME === "1"
      ? "PRAGMA synchronous = FULL" : "PRAGMA synchronous = NORMAL")
    yield* db.run("PRAGMA busy_timeout = 5000")
    yield* db.run("PRAGMA cache_size = -64000")
    yield* db.run("PRAGMA foreign_keys = ON")
    yield* db.run("PRAGMA wal_checkpoint(PASSIVE)")
    yield* DatabaseMigration.apply(db)

    return { db }
  }).pipe(Effect.orDie),
)

export function layerFromPath(filename: string) {
  return layer.pipe(Layer.provide(sqliteLayer({ filename })))
}

/** Host maintenance of an existing database without schema migration, WAL
 * mode changes or checkpoints. Read-only inspection must not mutate a source. */
export function layerFromExistingPath(filename: string, options: { readonly: boolean }) {
  return Layer.effect(Service, Effect.gen(function* () {
    const db = yield* makeDatabase
    yield* db.run("PRAGMA busy_timeout = 5000")
    if (!options.readonly) {
      yield* db.run("PRAGMA synchronous = FULL")
      yield* db.run("PRAGMA foreign_keys = ON")
    }
    return { db }
  }).pipe(Effect.orDie)).pipe(Layer.provide(sqliteLayer({
    filename, readonly: options.readonly, readwrite: !options.readonly, create: false, disableWAL: true,
  })))
}

export function path() {
  if (Flag.OPENCODE_DB) {
    if (Flag.OPENCODE_DB === ":memory:" || isAbsolute(Flag.OPENCODE_DB)) return Flag.OPENCODE_DB
    return join(Global.Path.data, Flag.OPENCODE_DB)
  }
  if (
    ["latest", "beta", "prod"].includes(InstallationChannel) ||
    process.env.OPENCODE_DISABLE_CHANNEL_DB === "1" ||
    process.env.OPENCODE_DISABLE_CHANNEL_DB === "true"
  )
    return join(Global.Path.data, "opencode.db")
  return join(Global.Path.data, `opencode-${InstallationChannel.replace(/[^a-zA-Z0-9._-]/g, "-")}.db`)
}

export const defaultLayer = Layer.unwrap(
  Effect.gen(function* () {
    return layerFromPath(path())
  }),
).pipe(Layer.provide(Global.defaultLayer))

export const node = makeGlobalNode({ service: Service, layer: layerFromPath(path()), deps: [] })
