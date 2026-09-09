import { expect, test } from "bun:test"
import type { Session } from "@opencode-ai/sdk/v2"
import { descendantActivity, isActiveTask, isRunningTask, readTaskDescendants } from "./native-task-tree"

const session = (id: string, parentID?: string): Session => ({ id, parentID, directory: "/fixture", projectID: "fixture",
  title: id, slug: id, version: "fixture", time: { created: 1, updated: 1 } })

test("an idle parent can stop its active grandchild without including unrelated busy sessions", async () => {
  const children: Record<string, Session[]> = { root: [session("child", "root")], child: [session("grandchild", "child")], grandchild: [] }
  const requested: string[] = []
  const descendants = await readTaskDescendants({ sessionID: "root", directory: "/fixture", signal: new AbortController().signal,
    children: async id => { requested.push(id); return children[id] ?? [] } })
  const activity = descendantActivity(descendants, { root: { type: "idle" }, child: { type: "idle" },
    grandchild: { type: "retry" }, unrelated: { type: "busy" } })
  expect(requested).toEqual(["root", "child", "grandchild"])
  expect(activity.items.map(item => [item.session.id, item.depth, item.live])).toEqual([
    ["child", 1, "idle"], ["grandchild", 2, "retry"],
  ])
  expect(activity.active).toBe(1)
  expect(isActiveTask("idle") || activity.active > 0).toBe(true)
})

test("mismatched children and aborted loads cannot become an apparently complete task tree", async () => {
  await expect(readTaskDescendants({ sessionID: "root", directory: "/fixture", signal: new AbortController().signal,
    children: async () => [session("unrelated", "other-root")] })).rejects.toThrow("父子关系")
  const controller = new AbortController()
  await expect(readTaskDescendants({ sessionID: "root", directory: "/fixture", signal: controller.signal,
    children: async () => { controller.abort(); return [session("child", "root")] } })).rejects.toThrow()
})

test("published running status keeps the task-tree stop action available during status races", () => {
  expect(isRunningTask("running")).toBe(true)
  expect(isRunningTask("busy")).toBe(true)
  expect(isRunningTask("idle")).toBe(false)
})
