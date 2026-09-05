import { execFile } from "node:child_process"
import { existsSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { promisify } from "node:util"

import type { Configuration } from "electron-builder"
import { resolveQuantCodeUpdateMode } from "./update-mode"

const execFileAsync = promisify(execFile)
const packageDir = path.dirname(fileURLToPath(import.meta.url))
const rootDir = path.resolve(packageDir, "../..")
const nativeDir = path.join(packageDir, "native")
const signScript = path.join(rootDir, "script", "sign-windows.ps1")
// The Electron 42 packaging update briefly installed Linux launchers/icons under
// "opencode-desktop". Keep that hidden desktop entry around so existing GNOME/KDE
// pins still resolve after the canonical app id changes back to ai.opencode.desktop.
const legacyDesktopEntry = path.join(packageDir, "resources", "linux", "opencode-desktop.desktop")
const legacyDesktopEntryFpm = `${legacyDesktopEntry}=/usr/share/applications/opencode-desktop.desktop`
const quantcodeMetainfo = path.join(packageDir, "resources", "org.hkust.quantcode.metainfo.xml")
const quantcodeMetainfoFpm = `${quantcodeMetainfo}=/usr/share/metainfo/org.hkust.quantcode.metainfo.xml`

async function signWindows(configuration: { path: string }) {
  if (process.platform !== "win32") return
  if (process.env.GITHUB_ACTIONS !== "true") return
  if (!process.env.AZURE_CLIENT_ID || !process.env.AZURE_TENANT_ID || !process.env.AZURE_SUBSCRIPTION_ID) return
  if (!process.env.AZURE_TRUSTED_SIGNING_ACCOUNT_NAME || !process.env.AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE) return
  if (!process.env.AZURE_TRUSTED_SIGNING_ENDPOINT) return
  if (!process.env.AZURE_TRUSTED_SIGNING_PUBLISHER_NAME) return

  await execFileAsync(
    "pwsh",
    ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", signScript, configuration.path],
    { cwd: rootDir },
  )
}

const channel = (() => {
  const raw = process.env.OPENCODE_CHANNEL
  if (raw === "dev" || raw === "beta" || raw === "prod" || raw === "quantcode") return raw
  if (raw === "latest") return "prod"
  return "quantcode"
})()
const updateMode = channel === "quantcode" ? resolveQuantCodeUpdateMode() : "signed"
// Linux SHA-512 updater metadata has no independent trust anchor, so Linux
// releases keep automatic updates disabled. Limit forceCodeSigning to targets
// that support the signing hooks used by the release workflow.
const forceCodeSigning =
  channel === "quantcode" && updateMode === "signed" && (process.platform === "darwin" || process.platform === "win32")

const APP_IDS = {
  dev: "ai.opencode.desktop.dev",
  beta: "ai.opencode.desktop.beta",
  prod: "ai.opencode.desktop",
  quantcode: "org.hkust.quantcode",
} as const

const getBase = (appId: string): Configuration => ({
  forceCodeSigning,
  artifactName:
    channel === "quantcode" ? "quantcode-${version}-${os}-${arch}.${ext}" : "opencode-desktop-${os}-${arch}.${ext}",
  directories: {
    output: "dist",
    buildResources: "resources",
  },
  // Linux launchers are .desktop files, so this is the desktop file name,
  // not just the app id. For prod, app id "ai.opencode.desktop" becomes
  // "ai.opencode.desktop.desktop".
  // https://developer.gnome.org/documentation/guidelines/maintainer/integrating.html
  // https://www.electron.build/docs/linux/
  extraMetadata: {
    desktopName: `${appId}.desktop`,
    // electron-builder derives the updater cache directory from the packaged
    // metadata name (not from publish options). Keep QuantCode's cache fully
    // separate from OpenCode's while preserving the OpenCode package name for
    // the other channels.
    ...(channel === "quantcode" ? { name: "quantcode" } : {}),
  },
  files: ["out/**/*", "resources/**/*"],
  extraResources: existsSync(nativeDir)
    ? [
        {
          from: "native/",
          to: "native/",
          filter: ["index.js", "index.d.ts", "build/Release/mac_window.node", "swift-build/**"],
        },
      ]
    : [],
  mac: {
    category: "public.app-category.developer-tools",
    icon: `resources/icons/icon.icns`,
    hardenedRuntime: true,
    gatekeeperAssess: false,
    entitlements: "resources/entitlements.plist",
    entitlementsInherit: "resources/entitlements.plist",
    notarize:
      channel === "quantcode"
        ? Boolean(
            process.env.APPLE_API_KEY &&
              existsSync(process.env.APPLE_API_KEY) &&
              process.env.APPLE_API_KEY_ID &&
              process.env.APPLE_API_ISSUER,
          )
        : true,
    target: ["dmg", "zip"],
  },
  dmg: {
    sign: true,
  },
  protocols: {
    name: "OpenCode",
    schemes: ["opencode"],
  },
  win: {
    icon: `resources/icons/icon.ico`,
    signtoolOptions: {
      sign: signWindows,
      signingHashAlgorithms: ["sha256"],
      publisherName:
        channel === "quantcode" && updateMode === "signed"
          ? process.env.AZURE_TRUSTED_SIGNING_PUBLISHER_NAME
          : undefined,
    },
    target: ["nsis"],
    verifyUpdateCodeSignature: channel === "quantcode" ? updateMode === "signed" : false,
  },
  nsis: {
    oneClick: true,
    perMachine: false,
    installerIcon: `resources/icons/icon.ico`,
    installerHeaderIcon: `resources/icons/icon.ico`,
  },
  linux: {
    icon: `resources/icons`,
    category: "Development",
    executableName: appId,
    // Keep the generated launcher filename aligned with extraMetadata.desktopName
    // and the AppStream launchable desktop-id.
    syncDesktopName: true,
    desktop: {
      entry: {
        // Match the installed .desktop file and hicolor icon basename so
        // Linux shells can associate the running Electron window with its launcher.
        StartupWMClass: appId,
      },
    },
    target: ["AppImage", "deb", "rpm"],
  },
})

function getConfig() {
  const appId = APP_IDS[channel]
  const base = getBase(appId)

  switch (channel) {
    case "dev": {
      return {
        ...base,
        appId,
        productName: "OpenCode Dev",
        rpm: { packageName: "opencode-dev" },
      }
    }
    case "beta": {
      return {
        ...base,
        appId,
        productName: "OpenCode Beta",
        protocols: { name: "OpenCode Beta", schemes: ["opencode"] },
        publish: { provider: "github", owner: "anomalyco", repo: "opencode-beta", channel: "latest" },
        rpm: { packageName: "opencode-beta" },
      }
    }
    case "prod": {
      return {
        ...base,
        appId,
        productName: "OpenCode",
        protocols: { name: "OpenCode", schemes: ["opencode"] },
        publish: { provider: "github", owner: "anomalyco", repo: "opencode", channel: "latest" },
        deb: { fpm: [legacyDesktopEntryFpm] },
        rpm: { packageName: "opencode", fpm: [legacyDesktopEntryFpm] },
      }
    }
    case "quantcode": {
      return {
        ...base,
        appId,
        productName: "QuantCode",
        protocols: { name: "QuantCode", schemes: ["quantcode"] },
        publish: {
          provider: "github",
          owner: "HKUST-QUANT-SOCIETY",
          repo: "quantcode",
          channel: "latest",
        },
        linux: {
          ...base.linux,
          executableName: "quantcode",
        },
        deb: { packageName: "quantcode", fpm: [quantcodeMetainfoFpm] },
        rpm: { packageName: "quantcode", fpm: [quantcodeMetainfoFpm] },
      }
    }
  }
}

export default getConfig()
