import { describe, expect, test } from "bun:test"
import type { QuantCodeSshLoginScan, QuantCodeSshLoginResult } from "../../identity"
import { SshOrgLoginWizard } from "./ssh-login"
import { createRoot } from 'solid-js'

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
  test('leaving before entry commits aborts the read; a committed server handoff may finish', async () => {
    for (const committed of [false, true]) {
      let dispose = () => {}, aborted = false
      const entered = Promise.withResolvers<void>()
      const view = createRoot(stop => {
        dispose = stop
        return SshOrgLoginWizard({ sshScan: async () => scan, sshConnect: async () => connected,
          onEnter: async (_result, signal, onCommit) => {
            if (committed) onCommit?.()
            signal!.addEventListener('abort', () => { aborted = true }, { once: true })
            entered.resolve()
            await new Promise(resolve => setTimeout(resolve, 5))
          } })
      })
      button(view, '重新登录').click(); await flush()
      button(view, 'Server B').click(); await entered.promise
      dispose()
      await new Promise(resolve => setTimeout(resolve, 10))
      expect(aborted).toBe(!committed)
    }
  })
  test('cancel after authentication keeps the session and resumes entry without signing again', async () => {
    let logins = 0, entries = 0
    const entered = Promise.withResolvers<void>()
    const view = SshOrgLoginWizard({ sshSelectKey: async () => true, sshScan: async () => scan,
      sshConnect: async () => { logins++; return connected }, onEnter: async (_result, signal) => {
        entries++
        if (entries !== 1) return
        entered.resolve()
        await new Promise<void>((_resolve, reject) => signal!.addEventListener('abort', () => reject(new Error('entry stopped')), { once: true }))
      } })
    button(view, '重新登录').click(); await flush()
    button(view, 'Server B').click(); await entered.promise
    button(view, '取消进入').click(); await flush()
    expect(view.textContent).toContain('组织会话仍有效')
    expect(button(view, '重新登录')).toBeUndefined()
    button(view, '继续进入工作区').click(); await flush()
    expect(logins).toBe(1)
    expect(entries).toBe(2)
  })
  test('a lost authentication response is reconciled and can be explicitly logged out', async () => {
    let issued = false, exits = 0, entries = 0
    const view = SshOrgLoginWizard({ sshScan: async () => scan,
      sshConnect: async () => { issued = true; throw new Error('认证结果尚未确认') },
      sshResolve: async () => issued ? connected : null,
      sshExitAttempt: async () => { exits++; issued = false }, onEnter: async () => { entries++ } })
    button(view, '重新登录').click(); await flush()
    button(view, 'Server B').click(); await flush(); await flush()
    expect(view.textContent).toContain('已认证为')
    expect(entries).toBe(0)
    button(view, '退出本次登录').click(); await flush()
    expect(exits).toBe(1)
    expect(button(view, '重新登录')).toBeTruthy()
  })
  test('pre-authentication errors stay visible after the result check finds no session', async () => {
    const view = SshOrgLoginWizard({ sshScan: async () => scan, sshConnect: async () => { throw new Error('公钥未登记') },
      sshResolve: async () => null, onEnter: async () => {} })
    button(view, '重新登录').click(); await flush()
    button(view, 'Server B').click(); await flush(); await flush()
    expect(view.querySelector('[role="alert"]')?.textContent).toContain('公钥未登记')
    expect(button(view, '重新登录')).toBeTruthy()
  })
  test('locked key offers native unlock and retries the same selection', async () => {
    let selected = 0, scans = 0, unlocked = 0
    const view = SshOrgLoginWizard({ sshSelectKey: async () => { selected++; return true },
      sshScan: async () => { if (++scans === 1) throw new Error('私钥需要解锁。'); return scan },
      sshUnlockKey: async () => { unlocked++ }, sshConnect: async () => connected, onEnter: async () => {} })
    button(view, '重新登录').click(); await flush()
    button(view, '在本机终端解锁私钥').click(); await flush()
    button(view, '重新探测所选身份').click(); await flush()
    expect(selected).toBe(1)
    expect(unlocked).toBe(1)
    expect(scans).toBe(2)
    expect(view.querySelectorAll('.qc-ssh-group-option')).toHaveLength(2)
  })
  test("key selection is a distinct phase and does not display stale restore logs as a scan", async () => {
    const picked = Promise.withResolvers<boolean>()
    const calls: unknown[] = []
    const view = SshOrgLoginWizard({ sshSelectKey: () => picked.promise,
      sshScan: async input => { calls.push(input); return scan }, sshConnect: async () => connected,
      sshProgress: async () => ["旧的恢复会话日志"], onEnter: async () => {} })
    button(view, "重新登录").click()
    await flush()
    expect(calls).toEqual([])
    expect(view.textContent).toContain("文件选择窗口")
    expect(view.textContent).not.toContain("正在探测")
    expect(view.textContent).not.toContain("旧的恢复")
    expect(button(view, "正在选择私钥")).toBeTruthy()
    picked.resolve(true)
    await flush()
    expect(calls).toEqual([{ chooseKey: false, username: undefined }])
  })
  test("cancelling the native picker returns to a usable login button", async () => {
    let scans = 0
    const view = SshOrgLoginWizard({ sshSelectKey: async () => false,
      sshScan: async () => { scans++; return scan }, sshConnect: async () => connected, onEnter: async () => {} })
    button(view, "重新登录").click()
    await flush()
    expect(scans).toBe(0)
    expect(button(view, "重新登录").disabled).toBe(false)
    expect(view.querySelector('[role="alert"]')).toBeNull()
  })
  test("a hanging scan can be cancelled; its late result cannot replace a later attempt", async () => {
    const pending = Promise.withResolvers<QuantCodeSshLoginScan>()
    let calls = 0, cancelled = 0
    const view = SshOrgLoginWizard({ sshSelectKey: async () => true,
      sshScan: async () => ++calls === 1 ? pending.promise : scan,
      sshCancel: async () => { cancelled++ }, sshConnect: async () => connected, onEnter: async () => {} })
    button(view, "重新登录").click()
    await flush()
    expect(button(view, "重新登录")).toBeTruthy()
    button(view, "取消本次登录").click()
    expect(button(view, "重新登录").disabled).toBe(false)
    expect(cancelled).toBe(1)
    pending.resolve(scan)
    await flush()
    expect(view.querySelector(".qc-ssh-group-option")).toBeNull()
    button(view, "重新登录").click()
    await flush()
    expect(view.querySelectorAll(".qc-ssh-group-option")).toHaveLength(2)
  })
  test("scan deadline restores the login form instead of leaving a permanent spinner", async () => {
    let cancelled = 0
    const view = SshOrgLoginWizard({ timeoutMs: 10, sshSelectKey: async () => true,
      sshScan: () => new Promise(() => {}), sshCancel: async () => { cancelled++ },
      sshConnect: async () => connected, onEnter: async () => {} })
    button(view, "重新登录").click()
    await new Promise(resolve => setTimeout(resolve, 35))
    expect(view.querySelector('[role="alert"]')?.textContent).toContain("超时")
    expect(button(view, "重新登录").disabled).toBe(false)
    expect(cancelled).toBe(1)
  })
  test("cancelled entry preserves an issued login for confirmation instead of claiming cancellation", async () => {
    const pending = Promise.withResolvers<QuantCodeSshLoginResult>()
    let entered = 0
    const view = SshOrgLoginWizard({ sshScan: async () => scan, sshConnect: () => pending.promise,
      sshCancel: async () => {}, onEnter: async () => { entered++ } })
    button(view, "重新登录").click()
    await flush()
    button(view, "Server B").click()
    button(view, "取消进入").click()
    pending.resolve(connected)
    await flush()
    expect(entered).toBe(0)
    expect(view.textContent).toContain('已认证为')
    expect(button(view, '继续进入工作区')).toBeTruthy()
    expect(button(view, '重新登录')).toBeUndefined()
  })
  test("administrators have one full-workspace login, with no work-versus-operations choice", async () => {
    let selected: unknown
    const view = SshOrgLoginWizard({
      sshScan: async () => ({ username: "quantadmin", servers: [], failed: [], administrators: [
        { id: "server-c", label: "Server C", host: "fixture", username: "quantadmin", systemGroups: ["sudo", "quant-admin"] },
      ] }),
      sshConnect: async input => { selected = input; return { ...connected, mode: "organization-admin" } },
      onEnter: async result => { expect(result.session).toBeTruthy() },
    })
    button(view, "重新登录").click()
    await flush()
    expect(view.querySelectorAll(".qc-ssh-admin-option").length).toBe(1)
    expect(view.textContent).not.toContain("服务器运维")
    expect(view.textContent).not.toContain("独立认证")
    button(view, "管理员登录").click()
    await flush()
    expect(selected).toEqual({ serverId: "server-c", administrator: "organization" })
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

test("connection details display main-process progress and remain available after scanning", async () => {
  const view = SshOrgLoginWizard({sshScan: async () => scan, sshConnect: async () => connected,
    sshProgress: async () => ["Server A SSH 身份验证通过", "已读取工作组授权"], onEnter: async () => {}})
  button(view, "重新登录").click()
  await flush()
  expect(view.querySelector("summary")?.textContent).toBe("SSH 连接详情")
  expect(view.querySelector(".qc-ssh-log")?.textContent).toContain("Server A SSH 身份验证通过")
  expect(view.textContent).toContain("已读取工作组授权")
})
