import path from "path"
import { fileURLToPath } from "url"

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const dir = path.resolve(__dirname, "..")

process.chdir(dir)

const modelsUrl = process.env.OPENCODE_MODELS_URL || "https://models.dev"
// QuantCode only accepts host-configured URL/API-key providers. An upstream
// catalog is not product configuration and must not vary with build-time HTTP
// responses or a developer's MODELS_DEV_API_JSON environment override.
export const modelsData = process.env.OPENCODE_CHANNEL === "quantcode"
  ? "{}"
  : process.env.MODELS_DEV_API_JSON
  ? await Bun.file(process.env.MODELS_DEV_API_JSON).text()
  : await fetch(`${modelsUrl}/api.json`).then((x) => x.text())
console.log(process.env.OPENCODE_CHANNEL === "quantcode" ? "Using QuantCode custom-provider catalog" : "Loaded models.dev snapshot")
