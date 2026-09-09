import { describe, expect, test } from "bun:test"
import { userFacingServiceError } from "./workspace-ui"

describe("userFacingServiceError", () => {
  test("hides production executor transport details", () => {
    expect(userFacingServiceError(new Error("Management request rejected (503)"), "fallback")).toContain("STAGING")
  })

  test("turns missing GitHub identity into an actionable message", () => {
    expect(userFacingServiceError(new Error("PermissionError: GitHub identity token is not connected"), "fallback"))
      .toContain("GitHub 身份尚未连接")
  })

  test("keeps a useful fallback for unknown failures", () => {
    expect(userFacingServiceError(undefined, "通道暂不可用")).toBe("通道暂不可用")
  })
})
