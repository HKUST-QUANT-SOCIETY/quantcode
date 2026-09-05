export function buildNodeDefines(modelsData: string, channel: string, version: string) {
  return {
    OPENCODE_MODELS_DEV: modelsData,
    OPENCODE_CHANNEL: JSON.stringify(channel),
    OPENCODE_VERSION: JSON.stringify(version),
  }
}
