import { afterEach, describe, expect, test } from "bun:test"

const previous = process.env.OPENCODE_CHANNEL

afterEach(() => {
  if (previous === undefined) delete process.env.OPENCODE_CHANNEL
  else process.env.OPENCODE_CHANNEL = previous
})

async function mainDefines(query: string) {
  const config = await import(`./electron.vite.config.ts?${query}`).then((module) => module.default)
  return config.main?.define as Record<string, string>
}

describe("Electron main channel branding", () => {
  test("defines both main and shared app brand channels for prod", async () => {
    process.env.OPENCODE_CHANNEL = "prod"
    const define = await mainDefines("main-brand=prod")
    expect(define["import.meta.env.OPENCODE_CHANNEL"]).toBe('"prod"')
    expect(define["import.meta.env.VITE_OPENCODE_CHANNEL"]).toBe('"prod"')
  })

  test("canonicalizes the legacy latest channel before bundling", async () => {
    process.env.OPENCODE_CHANNEL = "latest"
    const define = await mainDefines("main-brand=latest")
    expect(define["import.meta.env.OPENCODE_CHANNEL"]).toBe('"prod"')
    expect(define["import.meta.env.VITE_OPENCODE_CHANNEL"]).toBe('"prod"')
  })
})
