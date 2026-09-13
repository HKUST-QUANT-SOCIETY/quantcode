import { expect, test } from "bun:test"
import { ServerAdminView } from "./server-admin"
const flush = () => new Promise<void>(resolve => setTimeout(resolve, 0))
test("server switching uses the same administrator identity without another login", async () => {
  const calls: (string | undefined)[] = []
  const view = ServerAdminView({
    status: async input => {
      calls.push(input?.serverId)
      return { session: { username: "quantadmin", serverId: input?.serverId ?? "server-c", serverLabel: "Server", fingerprint: "fixture", expires_at: "2099-01-01T00:00:00Z" }, report: "Linux" }
    }, onDisconnected: () => {},
  })
  await flush()
  expect(view.textContent).toContain("管理员")
  expect(view.textContent).not.toContain("进入组织管理")
  expect(view.textContent).not.toContain("退出服务器运维")
  const select = view.querySelector<HTMLSelectElement>("select")!
  select.value = "server-a"
  select.dispatchEvent(new Event("change"))
  await flush()
  expect(calls).toEqual(["server-c", "server-a"])
})
