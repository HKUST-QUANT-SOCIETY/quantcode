import { describe, expect, test } from "bun:test"
import { assertUpdaterBundle } from "./assert-updater-bundle"

const valid = `
const quantCodeUpdaterEnabled = false;
const UPDATER_ENABLED = app.isPackaged && CHANNEL !== "dev" && quantCodeUpdaterEnabled;
`

describe("compiled updater policy assertion", () => {
  test("requires the QuantCode compile-time policy only for the QuantCode channel", () => {
    expect(() => assertUpdaterBundle(valid, "quantcode")).not.toThrow()
    expect(() => assertUpdaterBundle("const upstream = true", "prod")).not.toThrow()
    expect(() => assertUpdaterBundle("const upstream = true", "dev")).not.toThrow()
  })

  test("fails a QuantCode bundle that omitted or retained the runtime helper", () => {
    expect(() => assertUpdaterBundle("const upstream = true", "quantcode")).toThrow("missing the compiled")
    expect(() => assertUpdaterBundle(`${valid}\nisQuantCodeUpdaterEnabled()`, "quantcode")).toThrow(
      "runtime policy helper",
    )
  })
})
