import { expect, test } from "bun:test"
import type { Configuration } from "electron-builder"

const legacyDesktopEntry = "resources/linux/opencode-desktop.desktop"
const quantcodeMetainfo = "resources/org.hkust.quantcode.metainfo.xml"

const channels = [
  { channel: "dev", appId: "ai.opencode.desktop.dev", executableName: "ai.opencode.desktop.dev" },
  { channel: "beta", appId: "ai.opencode.desktop.beta", executableName: "ai.opencode.desktop.beta" },
  { channel: "prod", appId: "ai.opencode.desktop", executableName: "ai.opencode.desktop" },
  { channel: "quantcode", appId: "org.hkust.quantcode", executableName: "quantcode" },
] as const

for (const channel of channels) {
  test(`uses one Linux desktop identity for ${channel.channel}`, async () => {
    const previous = process.env.OPENCODE_CHANNEL
    process.env.OPENCODE_CHANNEL = channel.channel

    const module = await import(`./electron-builder.config.ts?channel=${channel.channel}`)
    const config = module.default as Configuration

    if (previous === undefined) delete process.env.OPENCODE_CHANNEL
    else process.env.OPENCODE_CHANNEL = previous

    expect(config.appId).toBe(channel.appId)
    expect(config.extraMetadata?.desktopName).toBe(`${channel.appId}.desktop`)
    expect(config.linux?.executableName).toBe(channel.executableName)
    expect(config.linux?.syncDesktopName).toBe(true)
    expect(config.linux?.desktop?.entry?.StartupWMClass).toBe(channel.appId)
  })
}

test("uses an isolated QuantCode identity and release feed", async () => {
  const previous = process.env.OPENCODE_CHANNEL
  process.env.OPENCODE_CHANNEL = "quantcode"

  const module = await import("./electron-builder.config.ts?identity=quantcode")
  const config = module.default as Configuration

  if (previous === undefined) delete process.env.OPENCODE_CHANNEL
  else process.env.OPENCODE_CHANNEL = previous

  expect(config.productName).toBe("QuantCode")
  expect(config.protocols).toEqual({ name: "QuantCode", schemes: ["quantcode"] })
  expect(config.artifactName).toBe("quantcode-${version}-${os}-${arch}.${ext}")
  expect(config.publish).toEqual({
    provider: "github",
    owner: "HKUST-QUANT-SOCIETY",
    repo: "quantcode",
    channel: "latest",
  })
  expect(config.extraMetadata?.name).toBe("quantcode")
  expect(config.linux?.executableName).toBe("quantcode")
  expect(config.deb?.packageName).toBe("quantcode")
  expect(config.rpm?.packageName).toBe("quantcode")
  expect(config.deb?.fpm?.[0]).toEndWith(`${quantcodeMetainfo}=/usr/share/metainfo/org.hkust.quantcode.metainfo.xml`)
  expect(config.rpm?.fpm?.[0]).toEndWith(`${quantcodeMetainfo}=/usr/share/metainfo/org.hkust.quantcode.metainfo.xml`)
  expect(config.win?.verifyUpdateCodeSignature).toBe(false)
  expect(config.forceCodeSigning).toBe(false)
  expect(config.win?.signtoolOptions?.publisherName).toBeUndefined()
  expect(config.win?.signtoolOptions?.signingHashAlgorithms).toEqual(["sha256"])
})

test("enables update signature verification for an explicit signed QuantCode build", async () => {
  const previousChannel = process.env.OPENCODE_CHANNEL
  const previousMode = process.env.QUANTCODE_SIGNED_RELEASE
  const previousPublisher = process.env.AZURE_TRUSTED_SIGNING_PUBLISHER_NAME
  const publisher = "CN=HKUST Quant Society, O=HKUST, C=HK"
  process.env.OPENCODE_CHANNEL = "quantcode"
  process.env.QUANTCODE_SIGNED_RELEASE = "true"
  process.env.AZURE_TRUSTED_SIGNING_PUBLISHER_NAME = publisher

  const config = await import("./electron-builder.config.ts?signed=quantcode")
    .then((module) => module.default as Configuration)
    .finally(() => {
      if (previousChannel === undefined) delete process.env.OPENCODE_CHANNEL
      else process.env.OPENCODE_CHANNEL = previousChannel
      if (previousMode === undefined) delete process.env.QUANTCODE_SIGNED_RELEASE
      else process.env.QUANTCODE_SIGNED_RELEASE = previousMode
      if (previousPublisher === undefined) delete process.env.AZURE_TRUSTED_SIGNING_PUBLISHER_NAME
      else process.env.AZURE_TRUSTED_SIGNING_PUBLISHER_NAME = previousPublisher
    })

  expect(config.win?.verifyUpdateCodeSignature).toBe(true)
  expect(config.forceCodeSigning).toBe(true)
  expect(config.win?.signtoolOptions?.publisherName).toBe(publisher)
  expect(config.win?.signtoolOptions?.signingHashAlgorithms).toEqual(["sha256"])
})

test("keeps a hidden prod launcher for old Linux pins", async () => {
  const previous = process.env.OPENCODE_CHANNEL
  process.env.OPENCODE_CHANNEL = "prod"

  const module = await import("./electron-builder.config.ts?compat=prod")
  const config = module.default as Configuration

  if (previous === undefined) delete process.env.OPENCODE_CHANNEL
  else process.env.OPENCODE_CHANNEL = previous

  expect(config.deb?.fpm?.[0]).toEndWith(`${legacyDesktopEntry}=/usr/share/applications/opencode-desktop.desktop`)
  expect(config.rpm?.fpm?.[0]).toEndWith(`${legacyDesktopEntry}=/usr/share/applications/opencode-desktop.desktop`)

  const desktop = await Bun.file(legacyDesktopEntry).text()
  expect(desktop).toContain("Exec=/opt/OpenCode/ai.opencode.desktop %U")
  expect(desktop).toContain("Icon=ai.opencode.desktop")
  expect(desktop).toContain("StartupWMClass=ai.opencode.desktop")
  expect(desktop).toContain("NoDisplay=true")
})

test("canonicalizes the legacy latest channel to the OpenCode prod package", async () => {
  const previous = process.env.OPENCODE_CHANNEL
  process.env.OPENCODE_CHANNEL = "latest"

  const config = await import("./electron-builder.config.ts?channel=legacy-latest").then(
    (module) => module.default as Configuration,
  )

  if (previous === undefined) delete process.env.OPENCODE_CHANNEL
  else process.env.OPENCODE_CHANNEL = previous

  expect(config.appId).toBe("ai.opencode.desktop")
  expect(config.productName).toBe("OpenCode")
  expect(config.artifactName).toBe("opencode-desktop-${os}-${arch}.${ext}")
})
