import { describe, expect, test } from "bun:test"
import { isAdminRole, resolveRole } from "./roles"

describe("QuantCode roles", () => {
  test("server-issued role values are preserved", () => {
    expect(resolveRole("approver")).toBe("approver")
    expect(resolveRole("admin")).toBe("admin")
    expect(resolveRole("analyst")).toBe("analyst")
  })

  test("ordinary identities map to analyst", () => {
    expect(resolveRole("Quant Society Member")).toBe("analyst")
    expect(resolveRole("researcher-chen")).toBe("analyst")
  })

  test("empty identity falls back to analyst", () => {
    expect(resolveRole("")).toBe("analyst")
  })

  test("identity labels cannot escalate to admin", () => {
    expect(resolveRole("admin-zhang")).toBe("analyst")
    expect(resolveRole("管理员")).toBe("analyst")
    expect(resolveRole("root")).toBe("analyst")
    expect(isAdminRole("admin-zhang")).toBe(false)
  })

  test("approver and analyst identities are not admin", () => {
    expect(isAdminRole("approver")).toBe(false)
    expect(isAdminRole("researcher-chen")).toBe(false)
    expect(isAdminRole("")).toBe(false)
  })
})
