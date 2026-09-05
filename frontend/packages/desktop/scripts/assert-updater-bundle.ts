#!/usr/bin/env bun

import type { Channel } from "./utils"
import { resolveChannel } from "./utils"

export function assertUpdaterBundle(bundle: string, channel: Channel) {
  if (channel !== "quantcode") return

  if (!/const quantCodeUpdaterEnabled = (true|false);/.test(bundle)) {
    throw new Error("updater bundle is missing the compiled QuantCode policy")
  }

  if (!/const UPDATER_ENABLED = app\.isPackaged && CHANNEL !== "dev" && quantCodeUpdaterEnabled;/.test(bundle)) {
    throw new Error("updater bundle does not consume the compiled QuantCode policy")
  }

  if (bundle.includes("isQuantCodeUpdaterEnabled")) {
    throw new Error("updater bundle contains the runtime policy helper; rebuild with the compiled policy")
  }
}

if (import.meta.main) {
  const bundlePath = process.env.QUANTCODE_MAIN_BUNDLE ?? "./out/main/index.js"
  const channel = resolveChannel()
  assertUpdaterBundle(await Bun.file(bundlePath).text(), channel)
  console.log(
    channel === "quantcode"
      ? `Updater bundle assertion passed: ${bundlePath}`
      : `Updater bundle assertion skipped: ${channel}`,
  )
}
