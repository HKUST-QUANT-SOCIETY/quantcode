import { resolveChannel } from "./utils"

const arg = process.argv[2]
const channel = arg === "dev" || arg === "beta" || arg === "prod" || arg === "quantcode" ? arg : resolveChannel()

const quantcode = channel === "quantcode"
const appId = quantcode
  ? "org.hkust.quantcode"
  : channel === "prod"
    ? "ai.opencode.desktop"
    : `ai.opencode.desktop.${channel}`
const productName = quantcode
  ? "QuantCode"
  : channel === "prod"
    ? "OpenCode"
    : `OpenCode ${channel.charAt(0).toUpperCase() + channel.slice(1)}`
const summary = quantcode
  ? "Multi-agent quantitative research workspace"
  : `Open source AI coding agent${channel !== "prod" ? ` (${channel})` : ""}`
const developerId = quantcode ? "org.hkust.quant-society" : "ly.anoma"
const developerName = quantcode ? "HKUST Quant Society" : "Anomaly Innovations Inc."
const description = quantcode
  ? "QuantCode is a multi-agent desktop workspace for quantitative research, reusable Skills, Memory, and governed research execution."
  : "OpenCode is an open source agent that helps you write and run code with any AI model."
const repo = quantcode ? "https://github.com/HKUST-QUANT-SOCIETY/quantcode" : "https://github.com/anomalyco/opencode"
const homepage = quantcode ? repo : "https://opencode.ai"

const xml = `<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>${appId}</id>

  <metadata_license>CC0-1.0</metadata_license>
  <project_license>MIT</project_license>

  <name>${productName}</name>
  <summary>${summary}</summary>

  <developer id="${developerId}">
    <name>${developerName}</name>
  </developer>

  <description>
    <p>
      ${description}
    </p>
  </description>

  <launchable type="desktop-id">${appId}.desktop</launchable>

  <content_rating type="oars-1.1" />

  <url type="bugtracker">${repo}/issues</url>
  <url type="homepage">${homepage}</url>
  <url type="vcs-browser">${repo}</url>
</component>
`

await Bun.write(`resources/${appId}.metainfo.xml`, xml)
console.log(`Generated metainfo for ${channel} at resources/${appId}.metainfo.xml`)
