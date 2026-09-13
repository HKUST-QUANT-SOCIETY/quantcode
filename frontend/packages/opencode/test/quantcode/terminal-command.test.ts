import { expect, test } from "bun:test"
import { execFileSync } from "node:child_process"
import { terminalCommand } from "../../src/quantcode/terminal-command"

const posixTest = process.platform === "win32" ? test.skip : test

posixTest("the sandbox terminal preserves literal shell arguments", () => {
  const literal = "quotes ' and $HOME and $(false); *\nsecond line"
  const command = terminalCommand("/usr/bin/printf", ["%s", literal], "linux")
  expect(execFileSync("/bin/sh", ["-c", command.args[4]], { encoding: "utf8" })).toBe(literal)
})

test("other platforms retain their existing terminal command", () => {
  expect(terminalCommand("/bin/zsh", ["-l"], "darwin")).toEqual({command: "/bin/zsh", args: ["-l"]})
})
