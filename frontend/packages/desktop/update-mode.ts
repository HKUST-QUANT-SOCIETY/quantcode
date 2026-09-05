export type QuantCodeUpdateMode = "signed" | "unsigned" | "disabled"
export type QuantCodeUpdateFeed = "public" | "disabled"

type Environment = Record<string, string | undefined>

const hasValues = (environment: Environment, keys: string[]) => keys.every((key) => Boolean(environment[key]))

/**
 * Resolve whether an installed QuantCode app can reach its update feed without
 * credentials. A private GitHub repository must remain disabled because a
 * desktop bundle cannot safely carry a long-lived repository token.
 */
export function resolveQuantCodeUpdateFeed(environment: Environment = process.env): QuantCodeUpdateFeed {
  const configured = environment.QUANTCODE_UPDATE_FEED
  if (configured === "public") return "public"
  if (configured === "disabled") return "disabled"
  if (environment.QUANTCODE_PUBLIC_RELEASES === "true") return "public"
  return "disabled"
}

export function isQuantCodeUpdaterEnabled(mode: QuantCodeUpdateMode, feed: QuantCodeUpdateFeed) {
  return mode === "signed" && feed === "public"
}

/**
 * Resolve the update trust mode while packaging. The result is compiled into
 * the main process so an installed app never depends on the build host's env.
 * An unsigned update path must be explicitly requested for local testing.
 */
export function resolveQuantCodeUpdateMode(
  environment: Environment = process.env,
  platform: NodeJS.Platform = process.platform,
): QuantCodeUpdateMode {
  if (environment.QUANTCODE_SIGNED_RELEASE === "true" && (platform === "darwin" || platform === "win32")) {
    return "signed"
  }

  const appleSigning = hasValues(environment, [
    "APPLE_CERTIFICATE",
    "APPLE_CERTIFICATE_PASSWORD",
    "APPLE_API_KEY_CONTENT",
    "APPLE_API_KEY_ID",
    "APPLE_API_ISSUER",
  ])
  const windowsSigning = hasValues(environment, [
    "AZURE_CLIENT_ID",
    "AZURE_TENANT_ID",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_TRUSTED_SIGNING_ACCOUNT_NAME",
    "AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE",
    "AZURE_TRUSTED_SIGNING_ENDPOINT",
    "AZURE_TRUSTED_SIGNING_PUBLISHER_NAME",
  ])

  if ((platform === "darwin" && appleSigning) || (platform === "win32" && windowsSigning)) return "signed"
  if (environment.QUANTCODE_UNSIGNED_BUILD === "true") return "unsigned"
  // electron-builder's Linux SHA-512 metadata checks file integrity against
  // the feed, but the feed itself has no independent trust anchor. Keep Linux
  // updater trust disabled until signed metadata or an equivalent mechanism is
  // implemented.
  return "disabled"
}
