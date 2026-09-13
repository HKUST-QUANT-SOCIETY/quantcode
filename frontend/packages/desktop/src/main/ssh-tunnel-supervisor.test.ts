import { expect, test } from "bun:test"
import { EventEmitter } from "node:events"
import { PassThrough } from "node:stream"
import type { ChildProcess } from "node:child_process"
import { superviseSshTunnel } from "./ssh-tunnel-supervisor"

function child() {
  const events = new EventEmitter()
  return Object.assign(events, { stderr: new PassThrough(), killed: false, exitCode: null as number | null, signalCode: null,
    kill() { this.killed = true; return true },
    exit(code = 255) { this.exitCode = code; events.emit("exit", code, null) },
  })
}
async function until(check: () => boolean) {
  const deadline = Date.now() + 1000
  while (!check()) { if (Date.now() > deadline) throw Error("Condition not reached"); await Bun.sleep(2) }
}
test("a lost SSH process reconnects once and advances the connection generation", async () => {
  const children: ReturnType<typeof child>[] = []
  const tunnel = superviseSshTunnel({ launch: () => { const p = child(); children.push(p); return p as unknown as ChildProcess },
    probe: async () => true, retryDelayMs: 5 })
  try {
    await tunnel.ensureConnected()
    expect(tunnel.status()).toMatchObject({ state: "connected", generation: 1 })
    children[0].exit()
    expect(tunnel.alive()).toBe(false)
    await tunnel.ensureConnected()
    expect(children).toHaveLength(2)
    expect(tunnel.status()).toMatchObject({ state: "connected", generation: 2 })
  } finally { tunnel.stop() }
})
test("host key or identity rejection stays offline instead of repeatedly authenticating", async () => {
  const p = child(); let launches = 0
  const tunnel = superviseSshTunnel({ launch: () => { launches++; return p as unknown as ChildProcess }, probe: async () => true, retryDelayMs: 5 })
  try {
    await tunnel.ensureConnected()
    p.stderr.write("Host key verification failed.")
    p.exit()
    expect(tunnel.status().state).toBe("offline")
    await expect(tunnel.ensureConnected()).rejects.toThrow("重新登录")
    await Bun.sleep(20)
    expect(launches).toBe(1)
  } finally { tunnel.stop() }
})

test("another listener cannot make an unauthenticated SSH attempt look connected", async () => {
  const p = child()
  const tunnel = superviseSshTunnel({ launch: () => p as unknown as ChildProcess, probe: async () => true,
    forwardingReady: text => text.includes("forwarding ready"), retryDelayMs: 5 })
  try {
    await Bun.sleep(10)
    expect(tunnel.alive()).toBe(false)
    p.stderr.write("Authenticated using publickey. forwarding ready")
    await tunnel.ensureConnected()
    expect(tunnel.alive()).toBe(true)
    p.exit()
    expect(tunnel.status().state).toBe("reconnecting")
  } finally { tunnel.stop() }
})
test("closing cancels reconnect and discards a late probe result", async () => {
  const probe = Promise.withResolvers<boolean>(); const p = child()
  const tunnel = superviseSshTunnel({ launch: () => p as unknown as ChildProcess, probe: () => probe.promise, retryDelayMs: 5 })
  const waiting = tunnel.ensureConnected()
  tunnel.stop()
  await expect(waiting).rejects.toThrow("关闭")
  probe.resolve(true)
  await Bun.sleep(20)
  expect(tunnel.status().state).toBe("closed")
  expect(tunnel.alive()).toBe(false)
  expect(p.killed).toBe(true)
})
test("explicit reconnect is serialized against the previous process exit", async () => {
  const children: ReturnType<typeof child>[] = []
  const tunnel = superviseSshTunnel({ launch: () => { const p = child(); children.push(p); return p as unknown as ChildProcess }, probe: async () => true, retryDelayMs: 5 })
  try {
    await tunnel.ensureConnected()
    const pending = tunnel.reconnect()
    children[0].exit()
    await pending
    await until(() => tunnel.alive())
    expect(children).toHaveLength(2)
    expect(tunnel.status().generation).toBe(2)
  } finally { tunnel.stop() }
})
