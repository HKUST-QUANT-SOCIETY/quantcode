import { describe, expect, test } from "bun:test"
import { spawn } from "../../src/pty/pty.bun"
import type { Exit } from "../../src/pty/pty"

const ptyTest = process.platform === "win32" ? test.skip : test

describe("Bun PTY exit delivery", () => {
  for (const code of [0, 4]) {
    ptyTest(`replays exit ${code} once to a late subscriber`, async () => {
      const proc = spawn("/usr/bin/env", ["sh", "-c", `exit ${code}`], {
        name: "xterm-256color", cwd: "/tmp", env: { PATH: "/usr/bin:/bin" },
      })
      try {
        const live: Exit[] = []
        const exited = new Promise<Exit>(resolve => proc.onExit(event => { live.push(event); resolve(event) }))
        expect(await exited).toEqual({ exitCode: code })
        const late: Exit[] = []
        const listener = proc.onExit(event => late.push(event))
        await Promise.resolve()
        expect(late).toEqual([{ exitCode: code }])
        proc.kill()
        await Promise.resolve()
        expect(live).toEqual([{ exitCode: code }])
        expect(late).toEqual([{ exitCode: code }])
        listener.dispose()
      } finally {
        proc.kill()
      }
    })
  }

  ptyTest("dispose cancels queued exit replay", async () => {
    const proc = spawn("/usr/bin/env", ["sh", "-c", "exit 4"], {
      name: "xterm-256color", cwd: "/tmp", env: { PATH: "/usr/bin:/bin" },
    })
    try {
      await new Promise<Exit>(resolve => proc.onExit(resolve))
      const late: Exit[] = []
      const listener = proc.onExit(event => late.push(event))
      listener.dispose()
      await Promise.resolve()
      expect(late).toEqual([])
    } finally {
      proc.kill()
    }
  })

  ptyTest("disposes live listeners and preserves the surviving subscriber", async () => {
    const proc = spawn("/bin/cat", [], { name: "xterm-256color", cwd: "/tmp" })
    try {
      const removed: Exit[] = []
      const listener = proc.onExit(event => removed.push(event))
      listener.dispose()
      const live: Exit[] = []
      const exited = new Promise<Exit>(resolve => proc.onExit(event => { live.push(event); resolve(event) }))
      proc.write("\u0004")
      expect(await exited).toEqual({ exitCode: 0 })
      proc.kill()
      expect(removed).toEqual([])
      expect(live).toEqual([{ exitCode: 0 }])
    } finally {
      proc.kill()
    }
  })
})
