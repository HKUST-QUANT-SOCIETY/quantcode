import { expect, test } from "bun:test"
import { chmod, mkdir, mkdtemp, rm } from "node:fs/promises"
import os from "node:os"
import path from "node:path"

const script = path.join(import.meta.dir, "finalize-latest-yml.ts")

const metadataFor = (files: Array<{ filename: string; content: string }>) =>
  [
    "version: 1.2.3",
    "files:",
    ...files.flatMap((file) => [
      `  - url: ${file.filename}`,
      `    sha512: ${new Bun.CryptoHasher("sha512").update(file.content).digest("base64")}`,
      `    size: ${Buffer.byteLength(file.content)}`,
    ]),
    "releaseDate: '2026-08-19T00:00:00.000Z'",
    "",
  ].join("\n")

test("merges macOS updater metadata and honors the release tag", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "quantcode-latest-yml-"))
  const metadataRoot = path.join(root, "metadata")
  const runnerTemp = path.join(root, "runner-temp")
  const bin = path.join(root, "bin")
  const captureDir = path.join(root, "captured")
  const log = path.join(root, "gh.log")

  try {
    await Promise.all([
      mkdir(path.join(metadataRoot, "latest-yml-aarch64-apple-darwin"), { recursive: true }),
      mkdir(path.join(metadataRoot, "latest-yml-x86_64-apple-darwin"), { recursive: true }),
      mkdir(path.join(metadataRoot, "latest-yml-x86_64-pc-windows-msvc"), { recursive: true }),
      mkdir(runnerTemp, { recursive: true }),
      mkdir(bin, { recursive: true }),
      mkdir(captureDir, { recursive: true }),
    ])

    await Bun.write(
      path.join(metadataRoot, "latest-yml-aarch64-apple-darwin", "latest-mac.yml"),
      `${metadataFor([
        { filename: "quantcode-1.2.3-mac-arm64.zip", content: "arm-zip" },
        { filename: "quantcode-1.2.3-mac-arm64.dmg", content: "arm-dmg" },
      ])}path: quantcode-1.2.3-mac-arm64.zip\nsha512: legacy-arm\n`,
    )
    await Bun.write(
      path.join(metadataRoot, "latest-yml-x86_64-apple-darwin", "latest-mac.yml"),
      `${metadataFor([
        { filename: "quantcode-1.2.3-mac-x64.zip", content: "x64-zip" },
        { filename: "quantcode-1.2.3-mac-x64.dmg", content: "x64-dmg" },
      ])}path: quantcode-1.2.3-mac-x64.zip\nsha512: legacy-x64\n`,
    )
    await Bun.write(
      path.join(metadataRoot, "latest-yml-x86_64-pc-windows-msvc", "latest.yml"),
      metadataFor([{ filename: "quantcode-1.2.3-win-x64.exe", content: "win-exe" }]),
    )

    const gh = path.join(bin, "gh")
    const ghScript = [
      "#!/bin/sh",
      'for arg in "$@"; do',
      '  case "$arg" in',
      '    *.yml) cp "$arg" "$GH_CAPTURE_DIR/$(basename "$arg")" ;;',
      "  esac",
      "done",
      'printf "%s\\n" "$*" >> "$GH_LOG"',
      "",
    ].join("\n")
    await Bun.write(gh, ghScript)
    await chmod(gh, 0o755)

    const child = Bun.spawn(["bun", script], {
      env: {
        ...process.env,
        PATH: `${bin}:${process.env.PATH ?? ""}`,
        LATEST_YML_DIR: metadataRoot,
        GH_REPO: "HKUST-QUANT-SOCIETY/quantcode",
        OPENCODE_VERSION: "1.2.3",
        RELEASE_TAG: "quantcode-v1.2.3",
        REQUIRED_TARGETS: "aarch64-apple-darwin,x86_64-apple-darwin,x86_64-pc-windows-msvc",
        RUNNER_TEMP: runnerTemp,
        GH_CAPTURE_DIR: captureDir,
        GH_LOG: log,
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [exitCode, stdout, stderr] = await Promise.all([
      child.exited,
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
    ])

    expect(exitCode).toBe(0)
    expect(stderr).toBe("")
    expect(stdout).toContain("uploaded latest-mac.yml")

    const merged = await Bun.file(path.join(captureDir, "latest-mac.yml")).text()
    expect(merged).toContain("quantcode-1.2.3-mac-arm64.dmg")
    expect(merged).toContain("quantcode-1.2.3-mac-x64.dmg")
    expect(merged.indexOf("mac-arm64")).toBeLessThan(merged.indexOf("mac-x64"))
    expect(merged).not.toContain("\npath:")
    expect(merged).not.toContain("\nsha512: legacy-")

    const windows = await Bun.file(path.join(captureDir, "latest.yml")).text()
    expect(windows).toContain("quantcode-1.2.3-win-x64.exe")

    const ghArgs = await Bun.file(log).text()
    expect(ghArgs).toContain("quantcode-v1.2.3")
    expect(ghArgs).not.toContain(" v1.2.3 ")
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test("fails closed when a required target metadata file is missing", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "quantcode-latest-yml-missing-"))
  const metadataRoot = path.join(root, "metadata")

  try {
    await mkdir(path.join(metadataRoot, "latest-yml-aarch64-apple-darwin"), { recursive: true })
    await Bun.write(
      path.join(metadataRoot, "latest-yml-aarch64-apple-darwin", "latest-mac.yml"),
      metadataFor([
        { filename: "quantcode-1.2.3-mac-arm64.zip", content: "arm-zip" },
        { filename: "quantcode-1.2.3-mac-arm64.dmg", content: "arm-dmg" },
      ]),
    )

    const child = Bun.spawn(["bun", script], {
      env: {
        ...process.env,
        LATEST_YML_DIR: metadataRoot,
        GH_REPO: "HKUST-QUANT-SOCIETY/quantcode",
        OPENCODE_VERSION: "1.2.3",
        REQUIRED_TARGETS: "aarch64-apple-darwin,x86_64-pc-windows-msvc",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [exitCode, stderr] = await Promise.all([child.exited, new Response(child.stderr).text()])

    expect(exitCode).not.toBe(0)
    expect(stderr).toContain("Missing updater metadata for x86_64-pc-windows-msvc")
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test("refuses a publish manifest unless the release path was signed", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "quantcode-release-policy-"))

  try {
    const child = Bun.spawn(["bun", script], {
      env: {
        ...process.env,
        LATEST_YML_DIR: root,
        OPENCODE_VERSION: "1.2.3",
        RELEASE_SIGNED: "false",
        PUBLISH_REQUESTED: "true",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [exitCode, stderr] = await Promise.all([child.exited, new Response(child.stderr).text()])

    expect(exitCode).not.toBe(0)
    expect(stderr).toContain("Publishing requires RELEASE_SIGNED=true")
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test("validates the complete installer set and writes SHA256SUMS before upload", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "quantcode-release-assets-"))
  const metadataRoot = path.join(root, "metadata")
  const assetRoot = path.join(root, "assets")
  const finalizedRoot = path.join(root, "finalized")
  const files = [
    "quantcode-1.2.3-mac-arm64.zip",
    "quantcode-1.2.3-mac-arm64.zip.blockmap",
    "quantcode-1.2.3-mac-arm64.dmg",
    "quantcode-1.2.3-mac-arm64.dmg.blockmap",
    "quantcode-1.2.3-mac-x64.zip",
    "quantcode-1.2.3-mac-x64.zip.blockmap",
    "quantcode-1.2.3-mac-x64.dmg",
    "quantcode-1.2.3-mac-x64.dmg.blockmap",
    "quantcode-1.2.3-win-x64.exe",
    "quantcode-1.2.3-win-x64.exe.blockmap",
  ].map((filename) => ({ filename, content: `fixture:${filename}` }))

  try {
    await Promise.all([
      mkdir(path.join(metadataRoot, "latest-yml-aarch64-apple-darwin"), { recursive: true }),
      mkdir(path.join(metadataRoot, "latest-yml-x86_64-apple-darwin"), { recursive: true }),
      mkdir(path.join(metadataRoot, "latest-yml-x86_64-pc-windows-msvc"), { recursive: true }),
      mkdir(assetRoot, { recursive: true }),
    ])
    await Promise.all(files.map((file) => Bun.write(path.join(assetRoot, file.filename), file.content)))
    await Bun.write(
      path.join(metadataRoot, "latest-yml-aarch64-apple-darwin", "latest-mac.yml"),
      metadataFor(
        files.filter((file) => file.filename.endsWith("mac-arm64.zip") || file.filename.endsWith("mac-arm64.dmg")),
      ),
    )
    await Bun.write(
      path.join(metadataRoot, "latest-yml-x86_64-apple-darwin", "latest-mac.yml"),
      metadataFor(
        files.filter((file) => file.filename.endsWith("mac-x64.zip") || file.filename.endsWith("mac-x64.dmg")),
      ),
    )
    await Bun.write(
      path.join(metadataRoot, "latest-yml-x86_64-pc-windows-msvc", "latest.yml"),
      metadataFor(files.filter((file) => file.filename.endsWith("win-x64.exe"))),
    )

    const child = Bun.spawn(["bun", script], {
      env: {
        ...process.env,
        LATEST_YML_DIR: metadataRoot,
        RELEASE_ASSET_DIR: assetRoot,
        FINALIZED_YML_DIR: finalizedRoot,
        UPLOAD_RELEASE_METADATA: "false",
        OPENCODE_VERSION: "1.2.3",
        REQUIRED_TARGETS: "aarch64-apple-darwin,x86_64-apple-darwin,x86_64-pc-windows-msvc",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [exitCode, stdout, stderr] = await Promise.all([
      child.exited,
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
    ])

    expect(exitCode).toBe(0)
    expect(stderr).toBe("")
    expect(stdout).toContain("finalized latest yml files")
    expect(await Bun.file(path.join(finalizedRoot, "latest-mac.yml")).exists()).toBe(true)
    expect(await Bun.file(path.join(finalizedRoot, "latest.yml")).exists()).toBe(true)

    const checksums = await Bun.file(path.join(finalizedRoot, "SHA256SUMS")).text()
    expect(checksums.trim().split("\n")).toHaveLength(13)
    for (const file of files) expect(checksums).toContain(`  ${file.filename}`)
    expect(checksums).toContain("  latest-mac.yml")
    expect(checksums).toContain("  latest.yml")
    expect(checksums).toContain("  release-manifest.json")

    const manifest = await Bun.file(path.join(finalizedRoot, "release-manifest.json")).json()
    expect(manifest).toMatchObject({
      schemaVersion: 2,
      product: "QuantCode",
      version: "1.2.3",
      release: { repository: "HKUST-QUANT-SOCIETY/quantcode", tag: "v1.2.3" },
      distribution: {
        releaseClass: "qa-unsigned",
        publishRequested: false,
        updateFeed: "disabled",
        platformTrust: {
          macos: "unsigned-qa",
          windows: "unsigned-qa",
          linux: "unsigned-qa",
        },
      },
    })
    expect(manifest.assets).toHaveLength(12)
    expect(manifest.assets.map((asset: { name: string }) => asset.name)).toContain("latest-mac.yml")

    const approvedRoot = path.join(root, "approved")
    const approved = Bun.spawn(["bun", script], {
      env: {
        ...process.env,
        LATEST_YML_DIR: metadataRoot,
        RELEASE_ASSET_DIR: assetRoot,
        FINALIZED_YML_DIR: approvedRoot,
        UPLOAD_RELEASE_METADATA: "false",
        OPENCODE_VERSION: "1.2.3",
        REQUIRED_TARGETS: "aarch64-apple-darwin,x86_64-apple-darwin,x86_64-pc-windows-msvc",
        RELEASE_SIGNED: "true",
        PUBLISH_REQUESTED: "true",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [approvedExit, approvedError] = await Promise.all([
      approved.exited,
      new Response(approved.stderr).text(),
    ])
    expect(approvedExit).toBe(0)
    expect(approvedError).toBe("")
    expect(await Bun.file(path.join(approvedRoot, "release-manifest.json")).json()).toMatchObject({
      schemaVersion: 2,
      distribution: {
        releaseClass: "approved-release",
        publishRequested: true,
        updateFeed: "disabled",
        platformTrust: {
          macos: "developer-id-notarized",
          windows: "azure-trusted-signing",
          linux: "approved-platform-unsigned",
        },
      },
    })
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test("fails closed when a required installer blockmap is missing", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "quantcode-release-assets-missing-"))
  const metadataRoot = path.join(root, "metadata")
  const assetRoot = path.join(root, "assets")
  const installer = {
    filename: "quantcode-1.2.3-win-x64.exe",
    content: "fixture:quantcode-1.2.3-win-x64.exe",
  }

  try {
    await Promise.all([
      mkdir(path.join(metadataRoot, "latest-yml-x86_64-pc-windows-msvc"), { recursive: true }),
      mkdir(assetRoot, { recursive: true }),
    ])
    await Bun.write(path.join(assetRoot, installer.filename), installer.content)
    await Bun.write(
      path.join(metadataRoot, "latest-yml-x86_64-pc-windows-msvc", "latest.yml"),
      metadataFor([installer]),
    )

    const child = Bun.spawn(["bun", script], {
      env: {
        ...process.env,
        LATEST_YML_DIR: metadataRoot,
        RELEASE_ASSET_DIR: assetRoot,
        UPLOAD_RELEASE_METADATA: "false",
        OPENCODE_VERSION: "1.2.3",
        REQUIRED_TARGETS: "x86_64-pc-windows-msvc",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [exitCode, stderr] = await Promise.all([child.exited, new Response(child.stderr).text()])

    expect(exitCode).not.toBe(0)
    expect(stderr).toContain("Missing release assets: quantcode-1.2.3-win-x64.exe.blockmap")
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test("validates Linux assets while retaining AppImage-only updater metadata", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "quantcode-linux-release-assets-"))
  const metadataRoot = path.join(root, "metadata")
  const assetRoot = path.join(root, "assets")
  const finalizedRoot = path.join(root, "finalized")
  const files = [
    "quantcode-1.2.3-linux-x86_64.AppImage",
    "quantcode-1.2.3-linux-amd64.deb",
    "quantcode-1.2.3-linux-x86_64.rpm",
  ].map((filename) => ({ filename, content: `fixture:${filename}` }))

  try {
    await Promise.all([
      mkdir(path.join(metadataRoot, "latest-yml-x86_64-unknown-linux-gnu"), { recursive: true }),
      mkdir(assetRoot, { recursive: true }),
    ])
    await Promise.all(files.map((file) => Bun.write(path.join(assetRoot, file.filename), file.content)))
    const appImage = files.find((file) => file.filename.endsWith(".AppImage"))!
    await Bun.write(
      path.join(metadataRoot, "latest-yml-x86_64-unknown-linux-gnu", "latest-linux.yml"),
      `${metadataFor(files)}path: ${appImage.filename}\nsha512: legacy-linux-appimage\n`,
    )

    const child = Bun.spawn(["bun", script], {
      env: {
        ...process.env,
        LATEST_YML_DIR: metadataRoot,
        RELEASE_ASSET_DIR: assetRoot,
        FINALIZED_YML_DIR: finalizedRoot,
        UPLOAD_RELEASE_METADATA: "false",
        OPENCODE_VERSION: "1.2.3",
        REQUIRED_TARGETS: "x86_64-unknown-linux-gnu",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [exitCode, stdout, stderr] = await Promise.all([
      child.exited,
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
    ])

    expect(exitCode).toBe(0)
    expect(stderr).toBe("")
    expect(stdout).toContain("finalized latest yml files")

    const latestLinux = await Bun.file(path.join(finalizedRoot, "latest-linux.yml")).text()
    expect(latestLinux).toContain("quantcode-1.2.3-linux-x86_64.AppImage")
    expect(latestLinux).toContain("path: quantcode-1.2.3-linux-x86_64.AppImage")
    expect(latestLinux).not.toContain("linux-amd64.deb")
    expect(latestLinux).not.toContain("linux-x86_64.rpm")

    const checksums = await Bun.file(path.join(finalizedRoot, "SHA256SUMS")).text()
    for (const file of files) expect(checksums).toContain(`  ${file.filename}`)
    expect(checksums).toContain("  latest-linux.yml")
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test("fails closed when a Linux deb or rpm asset is missing", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "quantcode-linux-release-assets-missing-"))
  const metadataRoot = path.join(root, "metadata")
  const assetRoot = path.join(root, "assets")
  const files = ["quantcode-1.2.3-linux-x86_64.AppImage", "quantcode-1.2.3-linux-amd64.deb"].map((filename) => ({
    filename,
    content: `fixture:${filename}`,
  }))
  const missingRpm = {
    filename: "quantcode-1.2.3-linux-x86_64.rpm",
    content: "fixture:quantcode-1.2.3-linux-x86_64.rpm",
  }

  try {
    await Promise.all([
      mkdir(path.join(metadataRoot, "latest-yml-x86_64-unknown-linux-gnu"), { recursive: true }),
      mkdir(assetRoot, { recursive: true }),
    ])
    await Promise.all(files.map((file) => Bun.write(path.join(assetRoot, file.filename), file.content)))
    await Bun.write(
      path.join(metadataRoot, "latest-yml-x86_64-unknown-linux-gnu", "latest-linux.yml"),
      metadataFor([...files, missingRpm]),
    )

    const child = Bun.spawn(["bun", script], {
      env: {
        ...process.env,
        LATEST_YML_DIR: metadataRoot,
        RELEASE_ASSET_DIR: assetRoot,
        UPLOAD_RELEASE_METADATA: "false",
        OPENCODE_VERSION: "1.2.3",
        REQUIRED_TARGETS: "x86_64-unknown-linux-gnu",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [exitCode, stderr] = await Promise.all([child.exited, new Response(child.stderr).text()])

    expect(exitCode).not.toBe(0)
    expect(stderr).toContain("Missing release assets: quantcode-1.2.3-linux-x86_64.rpm")
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test("fails closed when Linux updater metadata contains an extra AppImage", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "quantcode-linux-release-metadata-extra-"))
  const metadataRoot = path.join(root, "metadata")

  try {
    await mkdir(path.join(metadataRoot, "latest-yml-x86_64-unknown-linux-gnu"), { recursive: true })
    await Bun.write(
      path.join(metadataRoot, "latest-yml-x86_64-unknown-linux-gnu", "latest-linux.yml"),
      metadataFor([
        { filename: "quantcode-1.2.3-linux-x86_64.AppImage", content: "expected-appimage" },
        { filename: "quantcode-1.2.3-linux-amd64.deb", content: "expected-deb" },
        { filename: "quantcode-1.2.3-linux-x86_64.rpm", content: "expected-rpm" },
        { filename: "quantcode-1.2.3-linux-legacy.AppImage", content: "unexpected-appimage" },
      ]),
    )

    const child = Bun.spawn(["bun", script], {
      env: {
        ...process.env,
        LATEST_YML_DIR: metadataRoot,
        UPLOAD_RELEASE_METADATA: "false",
        OPENCODE_VERSION: "1.2.3",
        REQUIRED_TARGETS: "x86_64-unknown-linux-gnu",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [exitCode, stderr] = await Promise.all([child.exited, new Response(child.stderr).text()])

    expect(exitCode).not.toBe(0)
    expect(stderr).toContain(
      "Updater metadata entries mismatch for x86_64-unknown-linux-gnu",
    )
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test("fails closed when macOS updater metadata contains an unexpected URL", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "quantcode-mac-release-metadata-extra-"))
  const metadataRoot = path.join(root, "metadata")

  try {
    await mkdir(path.join(metadataRoot, "latest-yml-aarch64-apple-darwin"), { recursive: true })
    await Bun.write(
      path.join(metadataRoot, "latest-yml-aarch64-apple-darwin", "latest-mac.yml"),
      metadataFor([
        { filename: "quantcode-1.2.3-mac-arm64.zip", content: "expected-zip" },
        { filename: "quantcode-1.2.3-mac-arm64.dmg", content: "expected-dmg" },
        { filename: "https://example.test/quantcode-1.2.3-mac-arm64.zip", content: "unexpected-remote" },
      ]),
    )

    const child = Bun.spawn(["bun", script], {
      env: {
        ...process.env,
        LATEST_YML_DIR: metadataRoot,
        UPLOAD_RELEASE_METADATA: "false",
        OPENCODE_VERSION: "1.2.3",
        REQUIRED_TARGETS: "aarch64-apple-darwin",
      },
      stdout: "pipe",
      stderr: "pipe",
    })
    const [exitCode, stderr] = await Promise.all([child.exited, new Response(child.stderr).text()])

    expect(exitCode).not.toBe(0)
    expect(stderr).toContain("Updater metadata entries mismatch for aarch64-apple-darwin")
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
