#!/usr/bin/env bun

import { $ } from "bun"
import { createHash } from "node:crypto"
import { createReadStream } from "node:fs"
import { mkdir, readdir, stat } from "node:fs/promises"
import path from "path"

const dir = process.env.LATEST_YML_DIR!
if (!dir) throw new Error("LATEST_YML_DIR is required")

const version = process.env.OPENCODE_VERSION
if (!version) throw new Error("OPENCODE_VERSION is required")

const releaseAssetDir = process.env.RELEASE_ASSET_DIR
const upload = process.env.UPLOAD_RELEASE_METADATA !== "false"
const tag = process.env.RELEASE_TAG || `v${version}`
const releaseSigned = booleanEnvironment("RELEASE_SIGNED", false)
const publishRequested = booleanEnvironment("PUBLISH_REQUESTED", false)
const updateFeed = process.env.RELEASE_UPDATE_FEED ?? "disabled"
if (updateFeed !== "public" && updateFeed !== "disabled") {
  throw new Error(`Invalid RELEASE_UPDATE_FEED: ${updateFeed}`)
}
if (publishRequested && !releaseSigned) throw new Error("Publishing requires RELEASE_SIGNED=true")

type FileEntry = {
  url: string
  sha512: string
  size: number
  blockMapSize?: number
}

type LatestYml = {
  version: string
  files: FileEntry[]
  releaseDate: string
  path?: string
  sha512?: string
}

function parse(content: string): LatestYml {
  const lines = content.split("\n")
  let version = ""
  let releaseDate = ""
  let path = ""
  let sha512 = ""
  const files: FileEntry[] = []
  let current: Partial<FileEntry> | undefined

  const flush = () => {
    if (current?.url && current.sha512 && current.size) files.push(current as FileEntry)
    current = undefined
  }

  for (const line of lines) {
    const indented = line.startsWith("    ") || line.startsWith("  -")
    if (line.startsWith("version:")) version = line.slice("version:".length).trim()
    else if (line.startsWith("releaseDate:"))
      releaseDate = line.slice("releaseDate:".length).trim().replace(/^'|'$/g, "")
    else if (line.startsWith("path:")) {
      flush()
      path = line.slice("path:".length).trim()
    } else if (line.startsWith("sha512:")) {
      flush()
      sha512 = line.slice("sha512:".length).trim()
    } else if (line.trim().startsWith("- url:")) {
      flush()
      current = { url: line.trim().slice("- url:".length).trim() }
    } else if (indented && current && line.trim().startsWith("sha512:"))
      current.sha512 = line.trim().slice("sha512:".length).trim()
    else if (indented && current && line.trim().startsWith("size:"))
      current.size = Number(line.trim().slice("size:".length).trim())
    else if (indented && current && line.trim().startsWith("blockMapSize:"))
      current.blockMapSize = Number(line.trim().slice("blockMapSize:".length).trim())
    else if (!indented && current) flush()
  }
  flush()

  return {
    version,
    files,
    releaseDate,
    ...(path ? { path } : {}),
    ...(sha512 ? { sha512 } : {}),
  }
}

function serialize(data: LatestYml, includeTopLevel = false) {
  const lines = [`version: ${data.version}`, "files:"]
  for (const file of data.files) {
    lines.push(`  - url: ${file.url}`)
    lines.push(`    sha512: ${file.sha512}`)
    lines.push(`    size: ${file.size}`)
    if (file.blockMapSize) lines.push(`    blockMapSize: ${file.blockMapSize}`)
  }
  // A single-architecture feed can retain electron-builder's legacy
  // top-level path/sha512 fields. Never carry those fields into a merged feed:
  // they would point at only one of the architectures.
  if (includeTopLevel && data.path) lines.push(`path: ${data.path}`)
  if (includeTopLevel && data.sha512) lines.push(`sha512: ${data.sha512}`)
  lines.push(`releaseDate: '${data.releaseDate}'`)
  return lines.join("\n") + "\n"
}

async function read(subdir: string, filename: string): Promise<LatestYml | undefined> {
  const file = Bun.file(path.join(dir, subdir, filename))
  if (!(await file.exists())) return undefined
  return parse(await file.text())
}

type RequiredTarget = {
  metadata: string
  metadataSuffixes: string[]
  updaterSuffixes: string[]
  assetSuffixes: string[]
}

const requiredTargetSpecs: Record<string, RequiredTarget> = {
  "aarch64-apple-darwin": {
    metadata: "latest-mac.yml",
    metadataSuffixes: ["-mac-arm64.zip", "-mac-arm64.dmg"],
    updaterSuffixes: ["-mac-arm64.zip", "-mac-arm64.dmg"],
    assetSuffixes: ["-mac-arm64.zip", "-mac-arm64.zip.blockmap", "-mac-arm64.dmg", "-mac-arm64.dmg.blockmap"],
  },
  "x86_64-apple-darwin": {
    metadata: "latest-mac.yml",
    metadataSuffixes: ["-mac-x64.zip", "-mac-x64.dmg"],
    updaterSuffixes: ["-mac-x64.zip", "-mac-x64.dmg"],
    assetSuffixes: ["-mac-x64.zip", "-mac-x64.zip.blockmap", "-mac-x64.dmg", "-mac-x64.dmg.blockmap"],
  },
  "x86_64-pc-windows-msvc": {
    metadata: "latest.yml",
    metadataSuffixes: ["-win-x64.exe"],
    updaterSuffixes: ["-win-x64.exe"],
    assetSuffixes: ["-win-x64.exe", "-win-x64.exe.blockmap"],
  },
  "x86_64-unknown-linux-gnu": {
    metadata: "latest-linux.yml",
    // electron-updater uses AppImage metadata. DEB/RPM remain manually
    // installable release assets and are validated separately below.
    metadataSuffixes: ["-linux-x86_64.AppImage", "-linux-amd64.deb", "-linux-x86_64.rpm"],
    updaterSuffixes: ["-linux-x86_64.AppImage"],
    assetSuffixes: ["-linux-x86_64.AppImage", "-linux-amd64.deb", "-linux-x86_64.rpm"],
  },
  "aarch64-unknown-linux-gnu": {
    metadata: "latest-linux-arm64.yml",
    metadataSuffixes: ["-linux-arm64.AppImage", "-linux-arm64.deb", "-linux-aarch64.rpm"],
    updaterSuffixes: ["-linux-arm64.AppImage"],
    assetSuffixes: ["-linux-arm64.AppImage", "-linux-arm64.deb", "-linux-aarch64.rpm"],
  },
}

const requiredTargets = (process.env.REQUIRED_TARGETS ?? "")
  .split(",")
  .map((target) => target.trim())
  .filter(Boolean)
const targetIsActive = (target: string) => requiredTargets.length === 0 || requiredTargets.includes(target)

const requiredMetadata = new Map<string, LatestYml>()

for (const target of requiredTargets) {
  const spec = requiredTargetSpecs[target]
  if (!spec) throw new Error(`Unknown required updater target: ${target}`)

  const metadata = await read(`latest-yml-${target}`, spec.metadata)
  if (!metadata) {
    throw new Error(`Missing updater metadata for ${target}: ${spec.metadata}`)
  }
  if (metadata.version !== version) {
    throw new Error(`Updater metadata version mismatch for ${target}: expected ${version}, got ${metadata.version}`)
  }

  const expectedUrls = spec.metadataSuffixes.map((suffix) => `quantcode-${version}${suffix}`).sort()
  const actualUrls = metadata.files.map((file) => file.url).sort()
  if (actualUrls.length !== expectedUrls.length || actualUrls.some((url, index) => url !== expectedUrls[index])) {
    throw new Error(
      `Updater metadata entries mismatch for ${target}: expected ${expectedUrls.join(", ")}; got ${actualUrls.join(", ") || "none"}`,
    )
  }

  requiredMetadata.set(target, metadata)
}

if (releaseAssetDir) await validateReleaseAssets(releaseAssetDir, requiredTargets, requiredMetadata)

const output: Record<string, string> = {}

function appImageUpdaterMetadata(metadata: LatestYml, expectedFilename: string): LatestYml {
  const appImages = metadata.files.filter((file) => file.url.endsWith(".AppImage"))
  if (appImages.length !== 1 || appImages[0]?.url !== expectedFilename) {
    const found = appImages.map((file) => file.url).join(", ") || "none"
    throw new Error(`Linux updater metadata must contain only ${expectedFilename}; found: ${found}`)
  }
  const appImage = appImages[0]

  // electron-builder adds DEB/RPM files to the Linux feed when all three
  // targets are packaged together. They are release assets, not updater
  // targets: electron-updater must receive a single AppImage path and hash.
  return {
    version: metadata.version,
    files: [appImage],
    releaseDate: metadata.releaseDate,
    path: appImage.url,
    sha512: appImage.sha512,
  }
}

// Windows: merge arm64 + x64 into single file
const winX64 = targetIsActive("x86_64-pc-windows-msvc")
  ? await read("latest-yml-x86_64-pc-windows-msvc", "latest.yml")
  : undefined
const winArm64 = targetIsActive("aarch64-pc-windows-msvc")
  ? await read("latest-yml-aarch64-pc-windows-msvc", "latest.yml")
  : undefined
if (winX64 || winArm64) {
  const base = winArm64 ?? winX64!
  output["latest.yml"] = serialize({
    version: base.version,
    files: [...(winArm64?.files ?? []), ...(winX64?.files ?? [])],
    releaseDate: base.releaseDate,
  })
}

// Linux x64: retain the AppImage updater target only.
const linuxX64 = targetIsActive("x86_64-unknown-linux-gnu")
  ? await read("latest-yml-x86_64-unknown-linux-gnu", "latest-linux.yml")
  : undefined
if (linuxX64) {
  output["latest-linux.yml"] = serialize(
    appImageUpdaterMetadata(linuxX64, `quantcode-${version}-linux-x86_64.AppImage`),
    true,
  )
}

// Linux arm64: retain the AppImage updater target only.
const linuxArm64 = targetIsActive("aarch64-unknown-linux-gnu")
  ? await read("latest-yml-aarch64-unknown-linux-gnu", "latest-linux-arm64.yml")
  : undefined
if (linuxArm64) {
  output["latest-linux-arm64.yml"] = serialize(
    appImageUpdaterMetadata(linuxArm64, `quantcode-${version}-linux-arm64.AppImage`),
    true,
  )
}

// macOS: merge arm64 + x64 into single file
const macX64 = targetIsActive("x86_64-apple-darwin")
  ? await read("latest-yml-x86_64-apple-darwin", "latest-mac.yml")
  : undefined
const macArm64 = targetIsActive("aarch64-apple-darwin")
  ? await read("latest-yml-aarch64-apple-darwin", "latest-mac.yml")
  : undefined
if (macX64 || macArm64) {
  const base = macArm64 ?? macX64!
  output["latest-mac.yml"] = serialize({
    version: base.version,
    files: [...(macArm64?.files ?? []), ...(macX64?.files ?? [])],
    releaseDate: base.releaseDate,
  })
}

const outputDir = process.env.FINALIZED_YML_DIR ?? process.env.RUNNER_TEMP ?? "/tmp"
await mkdir(outputDir, { recursive: true })

const generated: string[] = []

for (const [filename, content] of Object.entries(output)) {
  const filepath = path.join(outputDir, filename)
  await Bun.write(filepath, content)
  generated.push(filepath)
}

if (releaseAssetDir) {
  const manifestFiles = [
    ...(await readdir(releaseAssetDir)).map((filename) => path.join(releaseAssetDir, filename)),
    ...generated,
  ].sort((a, b) => path.basename(a).localeCompare(path.basename(b)))
  const manifestPath = path.join(outputDir, "release-manifest.json")
  const sourceRepository = process.env.SOURCE_REPOSITORY ?? process.env.GITHUB_REPOSITORY ?? "local"
  const sourceCommit = process.env.SOURCE_COMMIT ?? process.env.GITHUB_SHA ?? "local"
  const workflowRunId = process.env.WORKFLOW_RUN_ID ?? process.env.GITHUB_RUN_ID ?? "local"
  const serverUrl = process.env.GITHUB_SERVER_URL ?? "https://github.com"
  const manifest = {
    schemaVersion: 2,
    product: "QuantCode",
    version,
    source: {
      repository: sourceRepository,
      commit: sourceCommit,
      ref: process.env.SOURCE_REF ?? process.env.GITHUB_REF ?? "local",
    },
    workflow: {
      runId: workflowRunId,
      runAttempt: process.env.WORKFLOW_RUN_ATTEMPT ?? process.env.GITHUB_RUN_ATTEMPT ?? "local",
      url: sourceRepository === "local" ? "local" : `${serverUrl}/${sourceRepository}/actions/runs/${workflowRunId}`,
    },
    release: {
      repository: process.env.TARGET_REPOSITORY ?? process.env.GH_REPO ?? "HKUST-QUANT-SOCIETY/quantcode",
      tag,
    },
    distribution: {
      releaseClass: releaseSigned ? "approved-release" : "qa-unsigned",
      publishRequested,
      updateFeed,
      platformTrust: {
        macos: releaseSigned ? "developer-id-notarized" : "unsigned-qa",
        windows: releaseSigned ? "azure-trusted-signing" : "unsigned-qa",
        linux: releaseSigned ? "approved-platform-unsigned" : "unsigned-qa",
      },
    },
    assets: await Promise.all(
      manifestFiles.map(async (file) => ({
        name: path.basename(file),
        size: (await stat(file)).size,
        sha256: await digest(file, "sha256", "hex"),
      })),
    ),
  }
  await Bun.write(manifestPath, JSON.stringify(manifest, null, 2) + "\n")
  generated.push(manifestPath)

  const files = [...manifestFiles, manifestPath]
  const checksums = await Promise.all(
    files
      .sort((a, b) => path.basename(a).localeCompare(path.basename(b)))
      .map(async (file) => `${await digest(file, "sha256", "hex")}  ${path.basename(file)}`),
  )
  const filepath = path.join(outputDir, "SHA256SUMS")
  await Bun.write(filepath, checksums.join("\n") + "\n")
  generated.push(filepath)
}

if (upload) {
  const repo = process.env.GH_REPO
  if (!repo) throw new Error("GH_REPO is required when UPLOAD_RELEASE_METADATA is enabled")
  for (const filepath of generated) {
    await $`gh release upload ${tag} ${filepath} --clobber --repo ${repo}`
    console.log(`uploaded ${path.basename(filepath)}`)
  }
}

console.log("finalized latest yml files")

async function validateReleaseAssets(assetDir: string, targets: string[], metadataByTarget: Map<string, LatestYml>) {
  const expected = targets
    .flatMap((target) => requiredTargetSpecs[target].assetSuffixes)
    .map((suffix) => `quantcode-${version}${suffix}`)
    .sort()
  const actual = (await readdir(assetDir)).sort()
  const missing = expected.filter((filename) => !actual.includes(filename))
  const unexpected = actual.filter((filename) => !expected.includes(filename))

  if (missing.length > 0) throw new Error(`Missing release assets: ${missing.join(", ")}`)
  if (unexpected.length > 0) throw new Error(`Unexpected release assets: ${unexpected.join(", ")}`)

  for (const target of targets) {
    const spec = requiredTargetSpecs[target]
    const metadata = metadataByTarget.get(target)!
    for (const suffix of spec.metadataSuffixes) {
      const filename = `quantcode-${version}${suffix}`
      const entry = metadata.files.find((file) => file.url === filename)!
      const filepath = path.join(assetDir, filename)
      const size = (await stat(filepath)).size
      if (entry.size !== size) {
        throw new Error(`Updater metadata size mismatch for ${filename}: expected ${size}, got ${entry.size}`)
      }

      const sha512 = await digest(filepath, "sha512", "base64")
      if (entry.sha512 !== sha512) throw new Error(`Updater metadata SHA-512 mismatch for ${filename}`)
    }
  }
}

async function digest(file: string, algorithm: "sha256" | "sha512", encoding: "hex" | "base64") {
  const hash = createHash(algorithm)
  for await (const chunk of createReadStream(file)) hash.update(chunk)
  return hash.digest(encoding)
}

function booleanEnvironment(name: string, fallback: boolean) {
  const value = process.env[name]
  if (value === undefined || value === "") return fallback
  if (value === "true") return true
  if (value === "false") return false
  throw new Error(`${name} must be true or false`)
}
