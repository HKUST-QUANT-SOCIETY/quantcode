import { afterEach, describe, expect, test } from "bun:test"
import { resolveChannel } from "./utils"

const previous = process.env.OPENCODE_CHANNEL

afterEach(() => {
  if (previous === undefined) delete process.env.OPENCODE_CHANNEL
  else process.env.OPENCODE_CHANNEL = previous
})

describe("desktop script channel resolution", () => {
  test("defaults unqualified fork builds to QuantCode", () => {
    delete process.env.OPENCODE_CHANNEL
    expect(resolveChannel()).toBe("quantcode")
  })

  test("canonicalizes the legacy latest channel to prod", () => {
    process.env.OPENCODE_CHANNEL = "latest"
    expect(resolveChannel()).toBe("prod")
  })
})
