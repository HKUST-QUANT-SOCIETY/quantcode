import { describe, expect, test } from "bun:test"
import { SshLoginView, stubSshConnect, type SshConnectFn, type SshIdentity } from "./ssh-login"

/** 与 zh.ts 同文案的测试用 t（组件要求注入 i18n，见 quantcode.ssh.* keys）。 */
const ZH: Record<string, string> = {
  "quantcode.ssh.host": "主机",
  "quantcode.ssh.user": "用户名",
  "quantcode.ssh.connect": "连接",
  "quantcode.ssh.connecting": "正在连接…",
  "quantcode.ssh.logWaiting": "等待服务器响应…",
  "quantcode.ssh.connected": "已连接",
  "quantcode.ssh.fingerprint": "指纹",
  "quantcode.ssh.groups": "组绑定",
  "quantcode.ssh.groupSuffix": "组",
  "quantcode.ssh.disconnect": "断开",
  "quantcode.ssh.failed": "连接失败",
  "quantcode.ssh.retry": "重试",
  "quantcode.ssh.reason.key_rejected": "密钥被拒",
  "quantcode.ssh.reason.host_unreachable": "主机不可达",
  "quantcode.ssh.reason.unavailable": "SSH 连接服务尚未就绪",
}
const t = (key: string) => ZH[key] ?? key

const IDENTITIES: SshIdentity[] = [
  { id: "analyst-key", label: "analyst-key · analyst@quant.internal", host: "quant.internal", user: "analyst" },
]

function mount(connect?: SshConnectFn, identities: SshIdentity[] = IDENTITIES) {
  const view = SshLoginView({ t, connect, identities })
  document.body.append(view)
  return view
}

function fillForm(view: HTMLElement) {
  const identity = view.querySelector<HTMLSelectElement>("#qc-ssh-identity")!
  identity.value = "analyst-key"
  identity.dispatchEvent(new Event("change"))
  return identity
}

const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

describe("SshLoginView", () => {
  test("without a desktop identity bridge, shows an explicit unavailable state", () => {
    const view = mount(undefined, [])
    expect(view.querySelector("#qc-ssh-identity")).toBeNull()
    expect(view.querySelector("#qc-ssh-key")).toBeNull()
    expect(view.textContent).toContain("SSH 连接服务尚未就绪")
    view.remove()
  })

  test("form state selects a local identity and never renders a private-key input", () => {
    const view = mount()
    expect(view.querySelector<HTMLSelectElement>("#qc-ssh-identity")).toBeTruthy()
    expect(view.querySelector("#qc-ssh-key")).toBeNull()
    expect(view.querySelector("input[type=password]")).toBeNull()

    const connect = view.querySelector<HTMLButtonElement>(".qc-button")!
    expect(connect.textContent).toBe("连接")
    expect(connect.disabled).toBe(false)
    view.remove()
  })

  test("default stub: identity selection → connecting → unavailable, without private-key handling", async () => {
    expect(stubSshConnect).toBeTruthy()
    const view = mount()
    fillForm(view)
    view.querySelector<HTMLButtonElement>(".qc-button")!.click()

    // 连接态：spinner + 逐行日志
    expect(view.querySelector(".qc-ssh-spinner")).toBeTruthy()
    const log = view.querySelector(".qc-ssh-log")!
    expect(log.textContent).toContain("ssh analyst@quant.internal")
    expect(log.textContent).toContain("等待服务器响应…")

    await flush()

    // 失败态：stub 返回 unavailable → 具体原因 + 重试
    expect(view.querySelector(".qc-status-error")?.textContent).toBe("连接失败")
    expect(view.querySelector(".qc-ssh-reason")?.textContent).toBe("SSH 连接服务尚未就绪")
    const retry = view.querySelector<HTMLButtonElement>(".qc-button")!
    expect(retry.textContent).toBe("重试")

    expect(view.textContent).not.toContain("private")
    retry.click()
    expect(view.querySelector<HTMLSelectElement>("#qc-ssh-identity")!.value).toBe("analyst-key")
    view.remove()
  })

  test("injected connect → connected state with fingerprint and group badges, disconnect returns to form", async () => {
    const view = mount(
      async () => ({ status: "connected", fingerprint: "SHA256:AbCd1234", groups: ["factor", "risk"] }),
    )
    fillForm(view)
    view.querySelector<HTMLButtonElement>(".qc-button")!.click()
    await flush()

    expect(view.querySelector(".qc-connection-pill")?.textContent).toContain("已连接")
    expect(view.querySelector(".qc-ssh-fingerprint")?.textContent).toBe("SHA256:AbCd1234")
    const badges = [...view.querySelectorAll(".qc-ssh-badge")].map((badge) => badge.textContent)
    expect(badges).toEqual(["factor 组", "risk 组"])

    view.querySelector<HTMLButtonElement>(".qc-button")!.click()
    expect(view.querySelector("#qc-ssh-identity")).toBeTruthy()
    view.remove()
  })

  test("injected connect failure surfaces specific reason (key rejected / host unreachable / raw fallback)", async () => {
    for (const [reason, expected] of [
      ["key_rejected", "密钥被拒"],
      ["host_unreachable", "主机不可达"],
      ["quota_exceeded", "quota_exceeded"],
    ] as const) {
      const view = mount(async () => ({ status: "error", reason }))
      fillForm(view)
      view.querySelector<HTMLButtonElement>(".qc-button")!.click()
      await flush()
      expect(view.querySelector(".qc-status-error")?.textContent).toBe("连接失败")
      expect(view.querySelector(".qc-ssh-reason")?.textContent).toBe(expected)
      view.remove()
    }
  })

  test("injected connect that throws lands in failure state instead of hanging", async () => {
    const view = mount(async () => {
      throw new Error("socket exploded")
    })
    fillForm(view)
    view.querySelector<HTMLButtonElement>(".qc-button")!.click()
    await flush()
    expect(view.querySelector(".qc-ssh-reason")?.textContent).toBe("主机不可达")
    view.remove()
  })
})
