import { expect, test } from "bun:test"
import { forwardArgvDeepLinks } from "./deep-links"

test("forwards matching deep links from process arguments", () => {
  const emitted: string[][] = []
  const urls = forwardArgvDeepLinks(
    [
      "C:\\Program Files\\QuantCode\\QuantCode.exe",
      "--flag",
      "quantcode://session/first",
      "opencode://session/upstream",
      "quantcode://session/second",
    ],
    "quantcode",
    (links) => emitted.push(links),
  )

  expect(urls).toEqual(["quantcode://session/first", "quantcode://session/second"])
  expect(emitted).toEqual([["quantcode://session/first", "quantcode://session/second"]])
})

test("does not emit when process arguments contain no matching deep links", () => {
  let calls = 0
  const urls = forwardArgvDeepLinks(["QuantCode.exe", "opencode://session/upstream"], "quantcode", () => calls++)

  expect(urls).toEqual([])
  expect(calls).toBe(0)
})
