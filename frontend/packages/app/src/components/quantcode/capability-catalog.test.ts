import { describe, expect, test } from "bun:test"
import {
  CapabilityCatalogView,
  capabilitiesFromTrace,
  type CapabilityCard,
  type CapabilityFetcher,
} from "./capability-catalog"
import type { RunAgentResult } from "./result-contract"

/** 与 zh.ts 同文案的测试用 t（组件要求注入 i18n，见 quantcode.capability.* keys）。 */
const ZH: Record<string, string> = {
  "quantcode.capability.title": "能力目录",
  "quantcode.capability.intro": "组织已登记的研究能力。方案制定前先查这里——能复用就别自造。",
  "quantcode.capability.searchPlaceholder": "搜索能力、接口面或用途…",
  "quantcode.capability.ownerGroup": "属组",
  "quantcode.capability.whenToUse": "何时用",
  "quantcode.capability.whenNotToReinvent": "何时别自造",
  "quantcode.capability.apiSurface": "接口面",
  "quantcode.capability.source": "source",
  "quantcode.capability.noMatch": "没有匹配的能力卡片。",
  "quantcode.capability.empty": "能力目录通道尚未接通：等待后端服务。",
  "quantcode.capability.loading": "正在加载能力目录…",
  "quantcode.capability.unavailable": "能力目录暂不可用：无法读取服务端目录。",
}
const t = (key: string) => ZH[key] ?? key

const CARD: CapabilityCard = {
  id: "quant-evaluator",
  name: "Quant Evaluator 批量因子评估器",
  type: "asset",
  api_surface: ["quant_evaluator.api：evaluate()（评估唯一入口）"],
  when_to_use: "因子批量评估需要 IC / 分位数 / 回撤等指标时",
  when_not_to_reinvent: "别自写 rank_ic / quantile_spread 等指标——注册表已覆盖",
  owner_group: "factor",
  source_commit: "73223a4",
  canonical_repo: "quant_evaluator",
  maturity_status: "PRODUCTION",
  integration_status: "PARTIAL",
}

function traceRun(resultJson: string): RunAgentResult {
  return {
    status: "completed",
    execution_trace: [
      { type: "agent_start", data: { task: "demo" } },
      { type: "tool_result", data: { tool: "list_capabilities", result: resultJson } },
    ],
  }
}

const mount = (props: { fetcher?: CapabilityFetcher; run?: RunAgentResult | null }) => {
  const view = CapabilityCatalogView({ t, ...props })
  document.body.append(view)
  return view
}

const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

describe("capabilitiesFromTrace", () => {
  test("extracts cards from list_capabilities tool_result events", () => {
    const cards = capabilitiesFromTrace(traceRun(JSON.stringify({ capabilities: [CARD] })))
    expect(cards).toHaveLength(1)
    expect(cards[0].name).toBe(CARD.name)
    expect(cards[0].when_not_to_reinvent).toBe(CARD.when_not_to_reinvent)
  })

  test("ignores other tools, non-JSON (truncated) results and malformed cards", () => {
    const run: RunAgentResult = {
      status: "completed",
      execution_trace: [
        { type: "tool_result", data: { tool: "run_agent", result: JSON.stringify({ capabilities: [CARD] }) } },
        { type: "tool_result", data: { tool: "list_capabilities", result: '{"capabilities": [{"name": "截断的卡' } },
        { type: "tool_result", data: { tool: "list_capabilities", result: JSON.stringify({ capabilities: [42, {}] }) } },
      ],
    }
    expect(capabilitiesFromTrace(run)).toHaveLength(0)
  })
})

describe("CapabilityCatalogView", () => {
  test("trace channel: renders cards with type badge, owner group and highlighted when-not-to-reinvent", () => {
    const view = mount({ run: traceRun(JSON.stringify([CARD])) })
    expect(view.querySelector(".qc-capability-card strong")?.textContent).toBe(CARD.name)
    expect(view.querySelectorAll(".qc-capability-card .qc-status")[0]?.textContent).toBe("asset")
    expect(view.textContent).toContain("maturity: PRODUCTION")
    expect(view.textContent).toContain("integration: PARTIAL")
    expect(view.textContent).toContain("quant_evaluator")
    expect(view.querySelector(".qc-capability-owner")?.textContent).toBe("属组: factor")
    const ban = view.querySelector(".qc-capability-ban")?.textContent ?? ""
    expect(ban).toContain("何时别自造")
    expect(ban).toContain("别自写 rank_ic")
    view.remove()
  })

  test("no channel data → empty placeholder (no fake data)", () => {
    const view = mount({ run: null })
    expect(view.querySelector(".qc-capability-empty h3")?.textContent).toBe(ZH["quantcode.capability.empty"])
    expect(view.querySelector(".qc-capability-list")).toBeNull()
    view.remove()
  })

  test("injectable fetcher takes precedence; unavailable does not fall back to stale trace", async () => {
    const fetchedCard: CapabilityCard = { name: "Data Access 数据接入", type: "asset", owner_group: "model" }
    const view = mount({
      run: traceRun(JSON.stringify([CARD])),
      fetcher: async () => [fetchedCard],
    })
    await flush()
    const names = [...view.querySelectorAll(".qc-capability-card strong")].map((el) => el.textContent)
    expect(names).toEqual(["Data Access 数据接入"])

    const view2 = mount({ run: traceRun(JSON.stringify([CARD])), fetcher: async () => null })
    await flush()
    expect(
      [...view2.querySelectorAll(".qc-capability-card strong")].map((el) => el.textContent ?? ""),
    ).toEqual([])
    expect(view2.textContent).toContain("能力目录暂不可用")
    view.remove()
    view2.remove()
  })

  test("search filters cards by name/api surface, no match shows its own empty state", () => {
    const view = mount({ run: traceRun(JSON.stringify([CARD])) })
    const search = view.querySelector<HTMLInputElement>(".qc-capability-search")!
    search.value = "evaluate"
    search.dispatchEvent(new Event("input"))
    expect(view.querySelectorAll(".qc-capability-card")).toHaveLength(1)

    search.value = "不存在的关键词"
    search.dispatchEvent(new Event("input"))
    expect(view.querySelectorAll(".qc-capability-card")).toHaveLength(0)
    expect(view.querySelector(".qc-capability-empty h3")?.textContent).toBe("没有匹配的能力卡片。")
    view.remove()
  })
})


test("reuse metadata is visible and canonical aliases are searchable", () => {
  const view = mount({ run: traceRun(JSON.stringify([{ ...CARD,
    inputs: ["FactorBatch", "LabelBundle"], outputs: ["EvaluationArtifact"],
    depends_on: ["data-access"], consumed_by: ["factor-assets"],
    deprecated_aliases: ["AutoFactorEvaluation"], observed_at: "2026-09-05",
  }])) })
  expect(view.textContent).toContain("LabelBundle")
  expect(view.textContent).toContain("EvaluationArtifact")
  expect(view.textContent).toContain("data-access")
  expect(view.textContent).toContain("2026-09-05")
  const input = view.querySelector<HTMLInputElement>("input")!
  for (const query of ["AutoFactorEvaluation", "quant_evaluator", "factor-assets"]) {
    input.value = query
    input.dispatchEvent(new Event("input"))
    expect(view.querySelectorAll(".qc-capability-card")).toHaveLength(1)
  }
  view.remove()
})
