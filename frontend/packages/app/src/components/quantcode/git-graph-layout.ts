export type GitCommit = { sha: string; message: string; parents: string[]; author?: string; date?: string }
export type GitHead = { branch: string; sha: string; changed?: boolean }

/** Child-before-parent ordering, even when branch responses overlap or clocks skew. */
export function layoutGitGraph(commits: GitCommit[], heads: GitHead[] = [], main?: string) {
  const nodes = new Map(commits.map(node => [node.sha, node]))
  const children = new Map([...nodes.keys()].map(sha => [sha, 0]))
  for (const node of nodes.values()) for (const parent of new Set(node.parents)) {
    if (nodes.has(parent)) children.set(parent, children.get(parent)! + 1)
  }
  const mainHead = heads.find(head => head.branch === main)?.sha
  const order = (a: GitCommit, b: GitCommit) =>
    (Number(b.sha === mainHead) - Number(a.sha === mainHead)) ||
    ((Date.parse(b.date ?? "") || 0) - (Date.parse(a.date ?? "") || 0)) || a.sha.localeCompare(b.sha)
  const ready = [...nodes.values()].filter(node => children.get(node.sha) === 0).sort(order)
  const sorted: GitCommit[] = []
  while (ready.length) {
    const node = ready.shift()!
    sorted.push(node)
    for (const parent of new Set(node.parents)) {
      if (!nodes.has(parent)) continue
      children.set(parent, children.get(parent)! - 1)
      if (children.get(parent) === 0) ready.push(nodes.get(parent)!)
    }
    ready.sort(order)
  }
  if (sorted.length !== nodes.size) throw new Error("提交父子关系包含循环，无法绘制 Git 图谱。")
  const lanes: (string | undefined)[] = []
  const rows = sorted.map((node, index) => {
    let lane = lanes.indexOf(node.sha)
    if (lane < 0) {
      lane = lanes.indexOf(undefined)
      if (lane < 0) lane = lanes.length
      lanes[lane] = node.sha
    }
    lanes[lane] = undefined
    node.parents.forEach((parent, i) => {
      if (lanes.includes(parent)) return
      const free = i === 0 ? lane : lanes.indexOf(undefined)
      lanes[free < 0 ? lanes.length : free] = parent
    })
    return { ...node, row: index, lane, heads: heads.filter(head => head.sha === node.sha) }
  })
  const positions = new Map(rows.map(row => [row.sha, row]))
  const edges = rows.flatMap(node => node.parents.map(parent => ({
    from: node, to: positions.get(parent), parent,
    lane: positions.get(parent)?.lane ?? Math.max(node.lane, lanes.indexOf(parent)),
  })))
  return { rows, edges, lanes: Math.max(1, ...rows.map(row => row.lane + 1), lanes.length) }
}
