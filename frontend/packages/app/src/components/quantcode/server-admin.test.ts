import { expect, test } from "bun:test"
import { ServerAdminView } from "./server-admin"
const flush = () => new Promise<void>(resolve => setTimeout(resolve, 0))

test("organization access errors keep the independently authenticated operations workspace usable", async () => {
  let exited = false
  const view = ServerAdminView({
    status: async () => ({ session: { username: "quantadmin", serverId: "server-c", serverLabel: "Server C", fingerprint: "fixture", expires_at: "2099-01-01T00:00:00Z" }, report: "Linux\nup 3 days" }),
    organization: async id => { expect(id).toBe("server-c"); throw new Error("Error invoking remote method 'quantcode-ssh-login-connect': Error: 组织管理通道尚未配置") },
    disconnect: async () => {}, onDisconnected: () => { exited = true },
  })
  await flush()
  expect(view.textContent).toContain("quantadmin · Server C")
  Array.from(view.querySelectorAll("button")).find(button => button.textContent === "进入组织管理")!.click()
  await flush()
  expect(view.querySelector('[role="alert"]')?.textContent).toBe("组织管理通道尚未配置")
  expect(view.textContent).toContain("up 3 days")
  expect(exited).toBe(false)
  Array.from(view.querySelectorAll("button")).find(button => button.textContent === "退出服务器运维")!.click()
  await flush()
  expect(exited).toBe(true)
})
