// QuantCode research PDF stub — 刘炽 / T3a
// Layout spec: templates/typst/research-layout.md
// Day 1: compile to blank/skeleton PDF (mock placeholders)

#let brand-red = rgb("#9B1E24")
#let text-gray = rgb("#3A3A3A")
#let mid-gray = rgb("#5E5E5E")
#let warm-paper = rgb("#F8F5F1")
#let warm-border = rgb("#EFE8DF")
#let footer-gray = rgb("#777777")

// --- Metadata (filled by research-pdf skill / ResearchSpec) ---
#let company-name = "【公司名称】"
#let security-id = "【证券代码】"
#let report-title = company-name + "：公司研究报告"
#let report-subtitle = "QuantCode Research PDF · Stub V0.1"
#let kicker = "COMPANY RESEARCH"
#let version = "V0.1"
#let status = "draft"
#let valuation-date = "【估值日 YYYY-MM-DD】"
#let report-date = "【报告日 YYYY-MM-DD】"
#let owner = "【负责人】"
#let reviewer = "【复核人】"

#let body-font = ("Times New Roman", "Kaiti SC", "Songti SC")
#let body-size = 10.2pt

#set text(font: body-font, size: body-size, lang: "zh", fill: text-gray)
#set par(justify: true, leading: 0.65em, spacing: 0.55em)

#let section-title(en, zh) = {
  set text(size: 8.5pt, fill: mid-gray)
  grid(
    columns: (1fr, 1fr),
    align(left)[#en],
    align(right)[#zh],
  )
  v(2mm)
  line(length: 100%, stroke: 1.2pt + brand-red)
  v(4mm)
}

#let h2-style = text.with(size: 18pt, weight: "bold", fill: brand-red)
#let h3-style = text.with(size: 13.2pt, weight: "bold", fill: rgb("#262626"))

#let section-heading(title) = {
  block(breakable: false)[
    #h2-style[#title]
    #v(1mm)
    #line(length: 100%, stroke: 0.5pt + warm-border)
    #v(3mm)
  ]
}

#let placeholder(body) = {
  block(
    fill: warm-paper,
    stroke: 0.5pt + warm-border,
    inset: 8pt,
    radius: 2pt,
  )[
    #set text(size: 9.5pt, fill: mid-gray, style: "italic")
    #body
  ]
}

#let meta-card(label, value) = {
  block(
    fill: warm-paper,
    stroke: 0.5pt + warm-border,
    inset: 10pt,
    radius: 2pt,
    width: 100%,
  )[
    #text(size: 8pt, fill: mid-gray, weight: "bold")[#label]
    #v(2mm)
    #text(size: 11.5pt, weight: "bold", fill: rgb("#111111"))[#value]
  ]
}

// --- Cover (no header/footer) ---
#page(margin: (top: 25.4mm, bottom: 25.4mm, left: 31.8mm, right: 31.8mm))[
  #text(size: 9pt, weight: "bold", fill: brand-red, tracking: 0.08em)[#kicker]
  #v(6mm)
  #text(size: 25pt, weight: "bold", fill: rgb("#111111"))[#report-title]
  #v(3mm)
  #text(size: 17pt, fill: mid-gray)[#report-subtitle]
  #v(8mm)
  #box(width: 100%, height: 1.8mm, fill: brand-red)
  #v(8mm)
  #grid(
    columns: (1fr, 1fr),
    gutter: 4mm,
    meta-card("证券代码", security-id),
    meta-card("版本 / 状态", version + " · " + status),
    meta-card("估值日", valuation-date),
    meta-card("报告日", report-date),
    meta-card("负责人", owner),
    meta-card("复核人", reviewer),
  )
  #v(10mm)
  #block(
    fill: rgb("#FBF1F1"),
    stroke: (left: 3pt + brand-red),
    inset: (left: 12pt, rest: 10pt),
  )[
  #text(size: 9.5pt)[
    *Day 1 stub*：章节骨架已预留，正文由 `fundamental:draft` + Prompt 05 填充后接入本模板。
  ]
  ]
]

// --- Body pages ---
#set page(
  paper: "a4",
  margin: (top: 25.4mm, bottom: 25.4mm, left: 31.8mm, right: 31.8mm),
  header: context {
    if counter(page).get().first() <= 1 { return }
    section-title("Company Research", "公司研究报告")
  },
  footer: context {
    if counter(page).get().first() <= 1 { return }
    set text(size: 8pt, fill: footer-gray)
    line(length: 100%, stroke: 0.5pt + rgb("#D9D9D9"))
    v(2mm)
    grid(
      columns: (1fr, auto),
      [HKUST QUANT SOCIETY · QuantCode Research],
      align(right)[
        #let p = counter(page).get().first()
        #if p < 10 [0#p] else [#p]
      ],
    )
  },
)

#outline(title: text(size: 18pt, weight: "bold", fill: brand-red)[目录], indent: 1.5em)
#pagebreak()

#let report-section(title, hint) = {
  section-heading(title)
  placeholder[（待填充）#hint]
  v(6mm)
}

#report-section("公司结论摘要", "公司本质、核心兑现、主要优势、问题与估值状态。")
#report-section("公司概览与商业模式", "产品、客户、收入模式、增长引擎。")
#report-section("行业映射与受益路径", "产业链位置及需求传导路径。")
#report-section("产品、客户与商业化证据链", "技术储备→订单→收入；禁止夸大阶段。")
#report-section("竞争格局", "直接竞争、替代技术、客户自研。")
#report-section("收入、毛利与费用拆解", "分业务/地区收入、扣非、非经常性损益。")
#report-section("现金流与资产质量", "应收、存货、经营现金流、CAPEX、ROE/ROIC。")
#report-section("管理层、治理与资本配置", "指引兑现、激励、并购、分红回购。")
#report-section("当前估值与市场隐含预期", "历史/可比估值、一致预期；*不写目标价与评级*。")
#report-section("主要风险", "行业、技术、客户、财务、治理、估值风险。")

#section-heading("附录")
#h3-style[待验证事项]
#placeholder[pending_confirmation 清单]
#v(4mm)
#h3-style[References]
#placeholder[Reference ID 列表，格式 REF-主题-序号]
#v(4mm)
#h3-style[结构化数据附件建议]
#placeholder[建议单独保存至 Excel 的表字段]
#v(4mm)
#h3-style[缺失信息与证据冲突]
#placeholder[资料缺口、来源冲突、口径问题]
#v(4mm)
#h3-style[必须人工确认]
#placeholder[商业化阶段、估值口径等人工确认项]

#pagebreak()
#section-heading("免责声明")
#set text(size: 8.5pt, fill: mid-gray)
本报告由 HKUST Quant Society Agent 辅助系统生成，仅供内部研究讨论，不构成任何证券买卖建议或投资建议。报告中的预测、估值与观点可能随时调整。投资者应独立判断并承担风险。未经书面许可，不得对外传播本报告全部或部分内容。

#v(4mm)
#text(size: 8pt, fill: footer-gray)[*草案，需合规复核后替换终稿。*]
