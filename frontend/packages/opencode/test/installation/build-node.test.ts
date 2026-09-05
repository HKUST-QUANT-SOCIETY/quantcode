import { randomUUID } from "node:crypto"
import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"
import { pathToFileURL } from "node:url"
import { expect, test } from "bun:test"
import { buildNodeDefines } from "../../script/node-build-config"

test("embeds the release version in the bundled node sidecar", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "opencode-sidecar-version-"))
  const version = "9.8.7-test.1"

  try {
    const entrypoint = path.join(directory, "entry.ts")
    const versionModule = path.resolve(import.meta.dir, "../../../core/src/installation/version.ts")
    await Bun.write(entrypoint, `export { InstallationVersion } from ${JSON.stringify(versionModule)}`)

    const result = await Bun.build({
      entrypoints: [entrypoint],
      outdir: path.join(directory, "out"),
      target: "node",
      format: "esm",
      define: buildNodeDefines("{}", "quantcode", version),
    })

    expect(result.success).toBe(true)
    const output = result.outputs.find((item) => item.path.endsWith("entry.js"))
    expect(output).toBeDefined()

    const bundled = await import(`${pathToFileURL(output!.path).href}?test=${randomUUID()}`)
    expect(bundled.InstallationVersion).toBe(version)
    expect(bundled.InstallationVersion).not.toBe("local")
  } finally {
    await rm(directory, { recursive: true, force: true })
  }
})
