export function resolveBrand(channel: ImportMetaEnv["VITE_OPENCODE_CHANNEL"]) {
  // Vite normally injects the channel. Treat an omitted channel as the
  // QuantCode default so an unqualified dev server cannot show OpenCode UI.
  const quantcode = channel == null || channel === "quantcode"
  return {
    isQuantCode: quantcode,
    name: quantcode ? "QuantCode" : "OpenCode",
    icon: quantcode ? "/quantcode-icon.png" : "https://opencode.ai/favicon-96x96-v3.png",
    feedbackUrl: quantcode
      ? "https://github.com/HKUST-QUANT-SOCIETY/quantcode/issues"
      : "https://opencode.ai/desktop-feedback",
    feedbackLabel: quantcode ? "GitHub Issues" : undefined,
    feedbackIcon: quantcode ? ("github" as const) : ("discord" as const),
  }
}

export function productCopy(value: string, productName: string) {
  const zen = "\u0000opencode-zen\u0000"
  return value.replaceAll("OpenCode Zen", zen).replaceAll("OpenCode", productName).replaceAll(zen, "OpenCode Zen")
}

const brand = resolveBrand(import.meta.env.VITE_OPENCODE_CHANNEL)

export const isQuantCode = brand.isQuantCode
export const PRODUCT_NAME = brand.name
export const PRODUCT_ICON = brand.icon
export const PRODUCT_FEEDBACK_URL = brand.feedbackUrl
export const PRODUCT_FEEDBACK_LABEL = brand.feedbackLabel
export const PRODUCT_FEEDBACK_ICON = brand.feedbackIcon
