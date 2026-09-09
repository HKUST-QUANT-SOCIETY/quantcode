import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises"
import { createHash } from "node:crypto"
import path from "node:path"
import { fileURLToPath } from "node:url"

const desktop = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const repository = path.resolve(desktop, "../../..")
const destination = path.join(desktop, "resources", "licenses")
const sources = [
  ["LICENSE", "quantcode-LICENSE.txt"],
  ["frontend/LICENSE", "opencode-LICENSE.txt"],
  ["frontend/packages/ui/LICENSE", "opencode-ui-LICENSE.txt"],
  ["frontend/packages/http-recorder/LICENSE", "opencode-http-recorder-LICENSE.txt"],
] as const

await mkdir(destination, { recursive: true })
const files = []
for (const [source, name] of sources) {
  const content = await readFile(path.join(repository, source))
  if (!content.length) throw new Error(`Required source license is empty: ${source}`)
  await writeFile(path.join(destination, name), content)
  files.push({ source, file: name, sha256: createHash("sha256").update(content).digest("hex") })
}
await copyFile(path.join(desktop, "resources", "NOTICES.md"), path.join(destination, "NOTICES.md"))
await writeFile(path.join(destination, "source-licenses.json"), JSON.stringify({
  version: 1,
  repository: "https://github.com/HKUST-QUANT-SOCIETY/quantcode",
  upstream: "https://github.com/anomalyco/opencode",
  release_provenance: "release-manifest.json accompanies the installer",
  files,
}, null, 2) + "\n")
