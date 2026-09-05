import { describe, expect, test } from "bun:test"
import { submitQuantCodeInstruction } from "./submission"

describe("submitQuantCodeInstruction", () => {
  test("distinguishes accepted and unavailable submissions", async () => {
    expect(await submitQuantCodeInstruction(() => true, "research")).toBe("accepted")
    expect(await submitQuantCodeInstruction(() => undefined, "research")).toBe("accepted")
    expect(await submitQuantCodeInstruction(() => false, "research")).toBe("unavailable")
  })

  test("contains synchronous and asynchronous failures", async () => {
    expect(
      await submitQuantCodeInstruction(() => {
        throw new Error("sync")
      }, "research"),
    ).toBe("failed")
    expect(await submitQuantCodeInstruction(async () => Promise.reject(new Error("async")), "research")).toBe(
      "failed",
    )
  })
})
