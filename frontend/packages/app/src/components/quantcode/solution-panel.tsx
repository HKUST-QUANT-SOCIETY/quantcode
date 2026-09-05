/**
 * P-10 方案面板：方案先行状态机可视化（会话内嵌，/solution 命令唤起）。
 *
 * 状态机：draft（黄点 + "方案未冻结，代码工具不可用"提示条）
 *   → 讨论轮次时间线（revise_solution feedback）
 *   → frozen（锁定徽章 + doc_hash 尾号）
 *   → 一致性 verdict 徽章（conformant 绿 / deviation 黄 + 偏离文件清单 / needs_human 红）。
 *
 * 数据源 = execution_trace 里 solution 四工具（draft/revise/freeze/status）的
 * tool_call（args.feedback 轮次时间线）与 tool_result 事件（solution_id /
 * solution_phase / doc_hash / rounds），以及一致性判定 tool_result 的
 * verdict/deviations 字段（runner/judge.SOLUTION_VERDICTS）。真实通道，不造假数据。
 * 纯 DOM 构建（沿 ssh-login 模式，bun test 兼容）。
 */
import type { TraceEvent } from "./result-contract"

export const SOLUTION_TOOLS = ["draft_solution", "revise_solution", "freeze_solution", "solution_status"] as const

export type SolutionVerdict = "conformant" | "deviation" | "needs_human"

export type SolutionRound = {
  feedback: string
  revision?: string
}

export type SolutionState = {
  solutionId?: string
  /** 后端 SolutionStatus：draft | frozen | superseded */
  phase?: string
  rounds: SolutionRound[]
  docHash?: string
  /** 超 max_rounds 仍处 draft 的人裁标记（后端 needs_human 字段） */
  needsHuman?: boolean
  verdict?: SolutionVerdict
  /** 一致性判定列出的偏离文件 */
  deviations: string[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isVerdict(value: unknown): value is SolutionVerdict {
  return value === "conformant" || value === "deviation" || value === "needs_human"
}

function parseToolResult(raw: unknown): Record<string, unknown> | undefined {
  if (typeof raw !== "string") return isRecord(raw) ? raw : undefined
  try {
    const parsed: unknown = JSON.parse(raw)
    return isRecord(parsed) ? parsed : undefined
  } catch {
    return undefined // 后端 tool_result 限长截断等 → 跳过，不造假数据
  }
}

/** 从 execution_trace 推导方案状态（纯函数，测试友好）。 */
export function deriveSolutionState(events?: TraceEvent[]): SolutionState {
  const state: SolutionState = { rounds: [], deviations: [] }
  for (const event of events ?? []) {
    const data = event.data
    if (!isRecord(data)) continue
    const tool = typeof data.tool === "string" ? data.tool : data.tool_name
    const isSolutionTool = typeof tool === "string" && (SOLUTION_TOOLS as readonly string[]).includes(tool)

    if (event.type === "tool_call" && tool === "revise_solution" && isRecord(data.args)) {
      const feedback = data.args.feedback
      if (typeof feedback === "string" && feedback.trim()) {
        state.rounds.push({
          feedback,
          revision: typeof data.args.revision === "string" && data.args.revision ? data.args.revision : undefined,
        })
      }
      continue
    }

    if (event.type !== "tool_result") continue

    // 一致性判定（judge_solution_conformance 结果可经任意工具回流，按字段识别）
    if (isVerdict(data.verdict)) {
      state.verdict = data.verdict
      state.deviations = Array.isArray(data.deviations) ? data.deviations.filter((d): d is string => typeof d === "string") : []
      continue
    }

    const result = parseToolResult(data.result)
    if (!result) continue

    // 一致性判定也可能包在 tool_result JSON 里
    if (isVerdict(result.verdict)) {
      state.verdict = result.verdict
      state.deviations = Array.isArray(result.deviations) ? result.deviations.filter((d): d is string => typeof d === "string") : []
      if (typeof result.doc_hash === "string") state.docHash = result.doc_hash
      continue
    }

    if (!isSolutionTool || result.ok !== true) continue
    if (typeof result.solution_id === "string") state.solutionId = result.solution_id
    if (typeof result.solution_phase === "string") state.phase = result.solution_phase
    else if (typeof result.status === "string") state.phase = result.status
    if (typeof result.doc_hash === "string" && result.doc_hash) state.docHash = result.doc_hash
    // needs_human 取最后一次 doc 载荷的当前值（冻结后会被后端清回 false）
    state.needsHuman = result.needs_human === true
  }
  return state
}

export type SolutionPanelProps = {
  /** i18n：panels 传 language.t（key 见 quantcode.solution.*） */
  t: (key: string) => string
  run?: { execution_trace?: TraceEvent[] } | null
}

const VERDICT_TONE: Record<SolutionVerdict, { chip: string; color: string }> = {
  conformant: { chip: "qc-status-completed", color: "#206b4a" },
  deviation: { chip: "qc-status-waiting_for_human", color: "#9a5b12" },
  needs_human: { chip: "qc-status-error", color: "#aa2e23" },
}

export function SolutionPanelView(props: SolutionPanelProps): HTMLElement {
  const t = props.t
  const root = document.createElement("div")
  root.className = "qc-solution-panel"
  root.style.cssText = "display:grid;gap:12px;align-content:start;"

  const state = deriveSolutionState(props.run?.execution_trace)
  const sectionLabel = (text: string) => {
    const span = document.createElement("span")
    span.className = "qc-section-label"
    span.textContent = text
    return span
  }
  const chip = (text: string, cls?: string, color?: string) => {
    const span = document.createElement("span")
    span.className = cls ? `qc-status ${cls}` : "qc-status"
    if (color) span.style.color = color
    span.textContent = text
    return span
  }

  if (!state.solutionId && state.rounds.length === 0) {
    // 还没有方案：占位 + /solution 命令引导（不发指令，命令在会话输入 /solution）
    const empty = document.createElement("div")
    empty.className = "qc-empty-state qc-solution-empty"
    const index = document.createElement("span")
    index.className = "qc-empty-index"
    index.textContent = "P-10"
    const title = document.createElement("h3")
    title.textContent = t("quantcode.solution.title")
    const desc = document.createElement("p")
    desc.style.cssText = "margin:0;font-size:11px;color:var(--qc-muted);"
    desc.textContent = t("quantcode.solution.empty")
    empty.append(index, title, desc)
    root.append(empty)
    return root
  }

  const intro = document.createElement("div")
  intro.className = "qc-memory-intro"
  intro.append(sectionLabel("SOLUTION WORKFLOW"), (() => {
    const title = document.createElement("h3")
    title.textContent = t("quantcode.solution.title")
    return title
  })())
  root.append(intro)

  if (state.solutionId) {
    const meta = document.createElement("div")
    meta.className = "qc-run-meta qc-solution-meta"
    const label = document.createElement("span")
    label.textContent = t("quantcode.solution.solutionId")
    const code = document.createElement("code")
    code.textContent = state.solutionId
    meta.append(label, code)
    root.append(meta)
  }

  // 阶段行：draft（黄点 + 提示条） / frozen（锁定徽章 + doc_hash 尾号）
  if (state.phase === "frozen" || state.phase === "superseded") {
    const frozenRow = document.createElement("div")
    frozenRow.className = "qc-solution-phase"
    frozenRow.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;align-items:center;"
    frozenRow.append(chip(`🔒 ${t("quantcode.solution.frozen")}`, "qc-status-completed"))
    if (state.docHash) {
      const hashLabel = sectionLabel(t("quantcode.solution.docHash"))
      const hash = document.createElement("code")
      hash.className = "qc-artifact qc-solution-doc-hash"
      hash.textContent = `…${state.docHash.slice(-8)}`
      frozenRow.append(hashLabel, hash)
    }
    root.append(frozenRow)
  } else {
    // draft（含 superseded 之外的未知阶段）→ 黄点 + 阶段限流提示条
    const draftRow = document.createElement("div")
    draftRow.className = "qc-solution-draft"
    draftRow.style.cssText = "display:grid;gap:6px;"

    const phaseLine = document.createElement("div")
    phaseLine.style.cssText = "display:flex;gap:8px;align-items:center;"
    const dot = document.createElement("i")
    dot.className = "qc-solution-dot"
    dot.style.cssText = "width:8px;height:8px;border-radius:999px;background:#9a5b12;display:inline-block;"
    phaseLine.append(dot, chip(t("quantcode.solution.draft"), "qc-status-waiting_for_human"))
    draftRow.append(phaseLine)

    const hint = document.createElement("p")
    hint.className = "qc-solution-draft-hint"
    hint.setAttribute("data-quantcode-draft-hint", "true")
    hint.style.cssText =
      "margin:0;padding:6px 8px;font-size:11px;color:#9a5b12;border:1px solid rgba(154,91,18,0.3);border-radius:6px;background:rgba(154,91,18,0.06);"
    hint.textContent = t("quantcode.solution.draftHint")
    draftRow.append(hint)
    root.append(draftRow)
  }

  // 讨论轮次时间线（feedback）
  if (state.rounds.length > 0) {
    root.append(sectionLabel(t("quantcode.solution.rounds")))
    const timeline = document.createElement("div")
    timeline.className = "qc-timeline qc-solution-rounds"
    state.rounds.forEach((round, index) => {
      const row = document.createElement("div")
      row.className = "qc-event-row qc-solution-round-row"
      const num = document.createElement("span")
      num.className = "qc-event-index"
      num.textContent = String(index + 1).padStart(2, "0")
      const copy = document.createElement("div")
      const feedback = document.createElement("strong")
      feedback.textContent = round.feedback
      copy.append(feedback)
      if (round.revision) {
        const revision = document.createElement("p")
        revision.textContent = `${t("quantcode.solution.revision")}：${round.revision}`
        copy.append(revision)
      }
      row.append(num, copy)
      timeline.append(row)
    })
    root.append(timeline)
  }

  // 一致性 verdict 徽章（needs_human 标记等价红色人裁态）
  const verdict: SolutionVerdict | undefined = state.verdict ?? (state.needsHuman ? "needs_human" : undefined)
  if (verdict) {
    const verdictRow = document.createElement("div")
    verdictRow.className = "qc-solution-verdict"
    verdictRow.style.cssText = "display:grid;gap:6px;"
    const tone = VERDICT_TONE[verdict]
    const badge = chip(
      verdict === "conformant"
        ? `✓ ${t("quantcode.solution.verdict.conformant")}`
        : verdict === "deviation"
          ? `⚠ ${t("quantcode.solution.verdict.deviation")}`
          : `✋ ${t("quantcode.solution.verdict.needs_human")}`,
      tone.chip,
      tone.color,
    )
    badge.classList.add("qc-solution-verdict-badge")
    verdictRow.append(badge)

    // deviation → 展开偏离文件清单（原生 details，免自造折叠）
    if (verdict === "deviation" && state.deviations.length > 0) {
      const details = document.createElement("details")
      details.className = "qc-solution-deviations"
      const summary = document.createElement("summary")
      summary.textContent = `${t("quantcode.solution.deviatedFiles")}（${state.deviations.length}）`
      details.append(summary)
      for (const file of state.deviations) {
        const code = document.createElement("code")
        code.className = "qc-artifact"
        code.textContent = file
        details.append(code)
      }
      verdictRow.append(details)
    }
    root.append(verdictRow)
  }

  return root
}
