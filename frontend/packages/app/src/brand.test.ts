import { describe, expect, test } from "bun:test"
import { productCopy, resolveBrand } from "./brand"

describe("QuantCode brand", () => {
  test("uses QuantCode identity and GitHub feedback", () => {
    expect(resolveBrand("quantcode")).toEqual({
      isQuantCode: true,
      name: "QuantCode",
      icon: "/quantcode-icon.png",
      feedbackUrl: "https://github.com/HKUST-QUANT-SOCIETY/quantcode/issues",
      feedbackLabel: "GitHub Issues",
      feedbackIcon: "github",
    })
  })

  test("defaults missing channel metadata to QuantCode", () => {
    expect(resolveBrand(undefined)).toMatchObject({
      isQuantCode: true,
      name: "QuantCode",
      feedbackLabel: "GitHub Issues",
      feedbackIcon: "github",
    })
  })

  test("rewrites upstream product references in localized copy", () => {
    expect(productCopy("请将此错误报告给 OpenCode 团队", "QuantCode")).toBe("请将此错误报告给 QuantCode 团队")
    expect(productCopy("Please report this error to the OpenCode team", "QuantCode")).toBe(
      "Please report this error to the QuantCode team",
    )
    expect(productCopy("OpenCode Zen works with OpenCode", "QuantCode")).toBe("OpenCode Zen works with QuantCode")
  })

  test("uses QuantCode document branding when no channel is supplied", async () => {
    const previous = process.env.OPENCODE_CHANNEL
    delete process.env.OPENCODE_CHANNEL
    const plugins = (await import("../vite.js" + "?quantcode-default-brand-test")).default as unknown[]
    if (previous === undefined) delete process.env.OPENCODE_CHANNEL
    if (previous !== undefined) process.env.OPENCODE_CHANNEL = previous

    const plugin = plugins.find(
      (item) => item && typeof item === "object" && "name" in item && item.name === "opencode-desktop:theme-preload",
    )
    if (
      !plugin ||
      typeof plugin !== "object" ||
      !("transformIndexHtml" in plugin) ||
      typeof plugin.transformIndexHtml !== "function"
    ) {
      throw new Error("QuantCode default title transform is missing")
    }

    expect(plugin.transformIndexHtml("<title>OpenCode</title>")).toContain("<title>QuantCode</title>")
  })

  test("rewrites document branding for the QuantCode channel", async () => {
    const previous = process.env.OPENCODE_CHANNEL
    process.env.OPENCODE_CHANNEL = "quantcode"
    const plugins = (await import("../vite.js" + "?quantcode-brand-test")).default as unknown[]
    if (previous === undefined) delete process.env.OPENCODE_CHANNEL
    if (previous !== undefined) process.env.OPENCODE_CHANNEL = previous

    const plugin = plugins.find(
      (item) => item && typeof item === "object" && "name" in item && item.name === "opencode-desktop:theme-preload",
    )
    if (
      !plugin ||
      typeof plugin !== "object" ||
      !("transformIndexHtml" in plugin) ||
      typeof plugin.transformIndexHtml !== "function"
    ) {
      throw new Error("QuantCode title transform is missing")
    }

    const html = plugin.transformIndexHtml(`
      <html>
        <head>
          <title>OpenCode</title>
          <link rel="icon" type="image/png" href="/favicon-96x96-v3.png" sizes="96x96" />
          <link rel="icon" type="image/svg+xml" href="/favicon-v3.svg" />
          <link rel="shortcut icon" href="/favicon-v3.ico" />
          <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon-v3.png" />
          <script id="oc-theme-preload-script" src="/oc-theme-preload.js"></script>
        </head>
        <body class="app"></body>
      </html>
    `)
    expect(html).toContain("<title>QuantCode</title>")
    expect(html).toContain('href="/quantcode-icon.png"')
    expect(html).not.toContain("favicon-v3")
    expect(html).not.toContain("apple-touch-icon-v3")
    expect(html).toContain('data-product="quantcode"')
  })

  test("keeps the shared desktop HTML OpenCode-branded for an explicit prod channel", async () => {
    const previous = process.env.OPENCODE_CHANNEL
    process.env.OPENCODE_CHANNEL = "prod"
    const plugins = (await import("../vite.js" + "?opencode-prod-brand-test")).default as unknown[]
    if (previous === undefined) delete process.env.OPENCODE_CHANNEL
    if (previous !== undefined) process.env.OPENCODE_CHANNEL = previous

    const plugin = plugins.find(
      (item) => item && typeof item === "object" && "name" in item && item.name === "opencode-desktop:theme-preload",
    ) as { transformIndexHtml?: (html: string) => string } | undefined
    if (!plugin?.transformIndexHtml) throw new Error("OpenCode prod title transform is missing")

    const source = await Bun.file("../desktop/src/renderer/index.html").text()
    const html = plugin.transformIndexHtml(source)
    expect(html).toContain("<title>OpenCode</title>")
    expect(html).toContain("./favicon-96x96-v3.png")
    expect(html).not.toContain("quantcode-icon.png")
    expect(html).not.toContain('data-product="quantcode"')
  })
})
