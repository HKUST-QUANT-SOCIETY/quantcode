import { describe, expect, test } from "bun:test"
import { openNativeDirectoryPicker } from "./directory-picker-native"
import { directoryPickerKind } from "./directory-picker-policy"

const local = {
  type: "sidecar",
  variant: "base",
  http: { url: "http://localhost:4096" },
} as const
const remote = {
  type: "ssh",
  host: "example.test",
  http: { url: "http://localhost:4096" },
} as const

describe("directoryPickerKind", () => {
  test("uses the native picker only for local desktop projects", () => {
    expect(directoryPickerKind("desktop", local)).toBe("native")
    expect(directoryPickerKind("desktop", remote)).toBe("server")
    expect(directoryPickerKind("web", local)).toBe("server")
  })
})

describe("openNativeDirectoryPicker", () => {
  test("returns the selected directory", async () => {
    const selected: Array<string | string[] | null> = []
    await openNativeDirectoryPicker(async () => "/repo", (result) => selected.push(result))
    expect(selected).toEqual(["/repo"])
  })

  test("turns rejected and synchronous picker failures into cancellation", async () => {
    const selected: Array<string | string[] | null> = []
    await openNativeDirectoryPicker(
      async () => {
        throw new Error("rejected")
      },
      (result) => selected.push(result),
    )
    await openNativeDirectoryPicker(
      () => {
        throw new Error("synchronous")
      },
      (result) => selected.push(result),
    )
    expect(selected).toEqual([null, null])
  })
})
