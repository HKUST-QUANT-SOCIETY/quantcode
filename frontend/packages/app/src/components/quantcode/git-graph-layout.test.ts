import { expect, test } from "bun:test"
import { layoutGitGraph } from "./git-graph-layout"
const node = (sha: string, parents: string[], date = "2026-09-08") => ({ sha, parents, date, message: sha })
test("linear history stays straight and deduplicates shared commits", () => {
  const graph = layoutGitGraph([node("a", ["b"]), node("b", ["c"]), node("c", []), node("b", ["c"])])
  expect(graph.rows.map(row => row.sha)).toEqual(["a", "b", "c"])
  expect(graph.rows.map(row => row.lane)).toEqual([0, 0, 0])
})
test("merge and divergent heads use separate tracks and converge on the common ancestor", () => {
  const graph = layoutGitGraph([node("base", []), node("left", ["base"]), node("right", ["base"]), node("merge", ["left", "right"])], [{ branch: "main", sha: "merge" }, { branch: "topic", sha: "right" }], "main")
  expect(graph.rows[0].sha).toBe("merge")
  expect(graph.rows.at(-1)?.sha).toBe("base")
  expect(graph.rows.find(row => row.sha === "left")?.lane).not.toBe(graph.rows.find(row => row.sha === "right")?.lane)
  expect(graph.edges.filter(edge => edge.to?.sha === "base")).toHaveLength(2)
  expect(graph.rows.find(row => row.sha === "right")?.heads[0].branch).toBe("topic")
})
test("parent chronology never reverses edges even with skewed timestamps", () => {
  const graph = layoutGitGraph([node("parent", [], "2030-01-01"), node("child", ["parent"], "2020-01-01"), node("other", ["parent"])])
  expect(graph.edges.every(edge => !edge.to || edge.from.row < edge.to.row)).toBe(true)
  expect(new Set(graph.rows.slice(0, 2).map(row => row.lane)).size).toBe(2)
})
test("missing parents remain explicit boundary edges; cyclic data is rejected", () => {
  expect(layoutGitGraph([node("tip", ["outside"])]).edges[0].to).toBeUndefined()
  expect(() => layoutGitGraph([node("a", ["b"]), node("b", ["a"])])).toThrow("循环")
})
