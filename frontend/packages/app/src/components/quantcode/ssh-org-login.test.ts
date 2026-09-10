import { describe, expect, test } from "bun:test"
import type { QuantCodeSshLoginScan, QuantCodeSshLoginResult } from "../../identity"
import { SshOrgLoginWizard } from "./ssh-login"

const flush = () => new Promise<void>(resolve => setTimeout(resolve, 0))
const scan: QuantCodeSshLoginScan = {
  username: "qc-fixture",
  servers: [
    { id: "server-a", label: "Server A", host: "a", username: "qc-fixture", groups: ["model"] },
    { id: "server-b", label: "Server B", host: "b", username: "qc-fixture", groups: ["model"] },
  ],
  failed: [],
}
const connected: QuantCodeSshLoginResult = {
  connection: { url: "http://127.0.0.1:48196", username: "quantcode", password: "fixture-access", displayName: "Server B" },
  session: { status: "connected", actor_id: "fixture", session_id: "a".repeat(32), fingerprint: "SHA256:fixture",
    group: "model", groups: ["model"], expires_at: "2099-01-01T00:00:00Z", execution_status: "disconnected" },
}
function button(view: HTMLElement, text: string) {
  return Array.from(view.querySelectorAll("button")).find(item => item.textContent?.includes(text))!
}

describe("organization login wizard", () => {
  test("administrators get separate organization and operations entries without Linux group choices", async () => {
    let selected: unknown
    const view = SshOrgLoginWizard({
      sshScan: async () => ({ username: "quantadmin", servers: [], failed: [], administrators: [
        { id: "server-c", label: "Server C", host: "fixture", username: "quantadmin", systemGroups: ["sudo", "quant-admin"] },
      ] }),
      sshConnect: async input => { selected = input; return { mode: "server-admin", admin: {
        username: "quantadmin", serverId: "server-c", serverLabel: "Server C", fingerprint: "fixture", expires_at: "2099-01-01T00:00:00Z",
      } } },
      onEnter: async result => { expect(result.mode).toBe("server-admin") },
    })
    button(view, "重新登录").click()
    await flush()
    expect(button(view, "组织管理")).toBeTruthy()
    expect(button(view, "服务器运维")).toBeTruthy()
    expect(view.textContent).not.toContain("sudo")
    expect(view.querySelector(".qc-ssh-group-option")).toBeNull()
    button(view, "服务器运维").click()
    await flush()
    expect(selected).toEqual({ serverId: "server-c", administrator: "servers" })
  })
  test("the workbench re-login action opens the picker without a second button", async () => {
    let scans = 0
    let started = 0
    SshOrgLoginWizard({ autoStart: true, onStarted: () => { started++ },
      sshScan: async () => { scans++; return null }, sshConnect: async () => connected, onEnter: async () => {} })
    await flush()
    expect(scans).toBe(1)
    expect(started).toBe(1)
  })
  test("native key selection cancellation stays on the form without an error", async () => {
    const calls: unknown[] = []
    const view = SshOrgLoginWizard({
      sshScan: async input => { calls.push(input); return null },
      sshConnect: async () => { throw new Error("must not connect") },
      onEnter: async () => {},
    })
    button(view, "重新登录").click()
    await flush()
    expect(calls).toEqual([{ chooseKey: true, username: undefined }])
    expect(view.querySelector('[role="alert"]')).toBeNull()
    expect(button(view, "重新登录")).toBeTruthy()
  })

  test("typing a corrected username enables retry and reuses the picked key", async () => {
    const calls: unknown[] = []
    const view = SshOrgLoginWizard({
      sshScan: async input => { calls.push(input); throw new Error("请检查 SSH 用户名") },
      sshConnect: async () => { throw new Error("must not connect") },
      onEnter: async () => {},
    })
    button(view, "重新登录").click()
    await flush()
    const field = view.querySelector<HTMLInputElement>('input[type="text"]')!
    field.value = "qc-fixture"
    field.dispatchEvent(new Event("input"))
    expect(button(view, "重新探测").disabled).toBe(false)
    button(view, "重新探测").click()
    await flush()
    expect(calls.at(-1)).toEqual({ chooseKey: false, username: "qc-fixture" })
    expect(view.querySelector('[role="alert"]')?.textContent).toContain("请检查 SSH 用户名")
  })

  test("same group on two hosts preserves the selected server and waits for authentication", async () => {
    const calls: unknown[] = []
    let finish: (value: typeof connected) => void = () => {}
    let entered: unknown
    const view = SshOrgLoginWizard({
      sshScan: async () => scan,
      sshConnect: input => { calls.push(input); return new Promise(resolve => { finish = resolve }) },
      onEnter: async result => { entered = result },
    })
    button(view, "重新登录").click()
    await flush()
    button(view, "Server B").click()
    expect(calls).toEqual([{ serverId: "server-b", group: "model" }])
    expect(view.textContent).not.toContain("登录成功")
    finish(connected)
    await flush()
    expect(button(view, "进入工作台")).toBeUndefined()
    expect(entered).toEqual(connected)
  })

  test("authentication failure returns to choices with the error and allows retry", async () => {
    let attempts = 0
    const view = SshOrgLoginWizard({
      sshScan: async () => scan,
      sshConnect: async () => { attempts++; throw new Error("组织身份服务拒绝登录") },
      onEnter: async () => { throw new Error("must not enter") },
    })
    button(view, "重新登录").click()
    await flush()
    button(view, "Server B").click()
    await flush()
    expect(view.querySelector('[role="alert"]')?.textContent).toContain("组织身份服务拒绝登录")
    expect(view.textContent).not.toContain("登录成功")
    button(view, "Server B").click()
    await flush()
    expect(attempts).toBe(2)
  })
})
