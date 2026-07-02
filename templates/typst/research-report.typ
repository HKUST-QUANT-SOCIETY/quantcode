// QuantCode research PDF — 刘炽 / T3a
// Layout spec: templates/typst/research-layout.md
// Day 2: figures, tables, footnotes / References sample content

#let brand-red = rgb("#9B1E24")
#let text-gray = rgb("#3A3A3A")
#let mid-gray = rgb("#5E5E5E")
#let warm-paper = rgb("#F8F5F1")
#let warm-border = rgb("#EFE8DF")
#let footer-gray = rgb("#777777")
#let gold-accent = rgb("#B88A2E")

// --- Metadata (filled by research-pdf skill / ResearchSpec) ---
#let company-name = "示例科技"
#let security-id = "0000.HK"
#let report-title = company-name + "：公司研究报告"
#let report-subtitle = "QuantCode Research PDF · Day 2 Sample"
#let kicker = "COMPANY RESEARCH"
#let version = "V0.2"
#let status = "draft"
#let valuation-date = "2026-06-28"
#let report-date = "2026-06-28"
#let owner = "刘炽"
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

// --- Day 2: reusable figure / table / citation components ---

#let table-font = ("Times New Roman", "Kaiti SC", "Songti SC")
#let table-size = 8.6pt
#let table-line = rgb("#D9D9D9")
#let table-border = rgb("#E8E8E8")

#let report-table(caption, columns, align, ..cells) = {
  set text(font: table-font, size: table-size, fill: text-gray)
  let ncol = columns.len()
  v(3mm)
  table(
    columns: columns,
    align: align,
    stroke: (x, y) => if y == 0 {
      (bottom: 1.3pt + table-line)
    } else {
      (bottom: 0.5pt + table-border)
    },
    inset: 6pt,
    fill: (x, y) => if y == 0 { warm-paper } else { none },
    table.header(..cells.pos().slice(0, ncol)),
    ..cells.pos().slice(ncol),
  )
  v(2mm)
  text(size: 8pt, fill: mid-gray)[#caption]
  v(4mm)
}

#let report-figure(caption, body) = {
  v(3mm)
  align(center)[#body]
  v(2mm)
  align(center)[#text(size: 8pt, fill: mid-gray)[#caption]]
  v(4mm)
}

#let cite(num) = super(size: 7pt)[#num]

#let ref-entry(num, ref-id, source) = {
  grid(
    columns: (auto, 1fr),
    column-gutter: 3mm,
    align(left)[#super(size: 7pt)[#num]],
    [#text(weight: "bold")[#ref-id] — #source],
  )
  v(2mm)
}

#let output-box(body) = {
  block(
    fill: warm-paper,
    stroke: (left: 2pt + gold-accent, rest: 0.5pt + warm-border),
    inset: (left: 10pt, rest: 8pt),
    radius: 2pt,
  )[
    #set text(size: 9.5pt, fill: text-gray)
    #body
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
      *Day 2 sample*：本章示范图表、脚注与 References 格式；其余章节仍保留占位框，待 `fundamental:draft` 接入后填充。
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

// --- Sample section: 公司结论摘要 (Day 2 demo) ---
#section-heading("公司结论摘要")

#output-box[
  *核心结论（推断）*：公司处于成长期，主业现金流改善，但海外产能爬坡节奏仍需验证#cite[3]。
]

#v(4mm)

示例科技是一家以高端制造为主业的上市公司，核心产品覆盖工业自动化与精密零部件两大板块#cite[1]。2024 年公司实现营业收入 165.0 亿元，同比增长 15.2%#cite[1]；毛利率 31.2%，与上年基本持平#cite[2]。

从商业化证据链看，*事实*层面公司已披露头部客户送样转量产订单#cite[4]；*市场共识*认为 2026 年产能利用率有望回升，但具体节奏仍属 *推断*，需结合订单与 capex 兑现交叉验证。

#report-figure(
  "图 1：收入结构示意（mock，单位：%）",
  box(
    width: 82%,
    height: 48mm,
    fill: warm-paper,
    stroke: 0.5pt + warm-border,
    radius: 2pt,
  )[
    #align(center + horizon)[
      #grid(
        columns: (1fr, 1fr, 1fr),
        column-gutter: 4mm,
        inset: 8pt,
        align(center)[
          #box(width: 100%, height: 28mm, fill: brand-red.lighten(55%), radius: 2pt)
          #v(2mm)
          #text(size: 8.5pt)[工业自动化 58%]
        ],
        align(center)[
          #box(width: 100%, height: 20mm, fill: rgb("#1F3A5F").lighten(65%), radius: 2pt)
          #v(2mm)
          #text(size: 8.5pt)[精密零部件 32%]
        ],
        align(center)[
          #box(width: 100%, height: 10mm, fill: gold-accent.lighten(50%), radius: 2pt)
          #v(2mm)
          #text(size: 8.5pt)[其他 10%]
        ],
      )
    ]
  ],
)

#v(6mm)

#report-section("公司概览与商业模式", "产品、客户、收入模式、增长引擎。")
#report-section("行业映射与受益路径", "产业链位置及需求传导路径。")
#report-section("产品、客户与商业化证据链", "技术储备→订单→收入；禁止夸大阶段。")
#report-section("竞争格局", "直接竞争、替代技术、客户自研。")

// --- Sample section: 收入拆解 + table (Day 2 demo) ---
#section-heading("收入、毛利与费用拆解")

下表为分业务收入拆解（mock 数据，仅供版式验收）。完整估值矩阵与盈利模型建议单独保存至 Excel，正文仅引用表号与 Reference ID#cite[1]。

#report-table(
  "表 1：分业务收入与毛利率（mock，单位：亿元）",
  (1.2fr, 1fr, 1fr, 1fr),
  (left, right, right, right),
  [业务板块], [2024 收入], [同比增速], [毛利率],
  [工业自动化], [95.7], [+18%], [33.1%],
  [精密零部件], [52.8], [+9%], [28.4%],
  [其他], [16.5], [+6%], [22.0%],
  [合计], [165.0], [+15.2%], [31.2%],
)

资料来源：公司公告#cite[2]；部分分项为管理层披露口径，与年报合并报表可能存在汇总差异（*pending_confirmation*）。

#v(2mm)

#report-section("现金流与资产质量", "应收、存货、经营现金流、CAPEX、ROE/ROIC。")
#report-section("管理层、治理与资本配置", "指引兑现、激励、并购、分红回购。")
#report-section("当前估值与市场隐含预期", "历史/可比估值、一致预期；*不写目标价与评级*。")
#report-section("主要风险", "行业、技术、客户、财务、治理、估值风险。")

#section-heading("附录")
#h3-style[待验证事项]
- 海外新产线投产节奏与 2026 年产能利用率指引#cite[3]（*pending_confirmation*）
- 精密零部件业务毛利率是否受原材料价格波动影响（口径待核对）
#v(4mm)

#h3-style[References]
#ref-entry(1, "REF-DEMO-0001", "公司 2024 年年报，合并利润表及分部信息，第 23–28 页")
#ref-entry(2, "REF-DEMO-0002", "公司 2024 年度业绩公告，2025-03-15")
#ref-entry(3, "REF-DEMO-0003", "公司 2025 年一季度业绩说明会纪要（管理层口头指引，待书面确认）")
#ref-entry(4, "REF-DEMO-0004", "公司关于重大合同签署的自愿性公告，2024-11-02")
#v(4mm)

#h3-style[结构化数据附件建议]
- `估值矩阵_SEC-0000.xlsx` — 可比公司 PE/PB、历史分位
- `盈利模型_SEC-0000.xlsx` — 分业务收入、毛利率、费用率假设
#v(4mm)

#h3-style[缺失信息与证据冲突]
- 分部收入与合并报表汇总口径存在 0.3% 以内四舍五入差异，不影响结论方向
#v(4mm)

#h3-style[必须人工确认]
- 商业化阶段：送样转量产是否已在全部核心客户完成验证
- 估值口径：是否采用扣非净利润作为可比估值基准

#pagebreak()
#section-heading("免责声明")
#set text(size: 8.5pt, fill: mid-gray)
本报告由 HKUST Quant Society Agent 辅助系统生成，仅供内部研究讨论，不构成任何证券买卖建议或投资建议。报告中的预测、估值与观点可能随时调整。投资者应独立判断并承担风险。未经书面许可，不得对外传播本报告全部或部分内容。

#v(4mm)
#text(size: 8pt, fill: footer-gray)[*草案，需合规复核后替换终稿。*]
