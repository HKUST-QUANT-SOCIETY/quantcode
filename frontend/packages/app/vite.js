import { readFileSync } from "node:fs"
import solidPlugin from "vite-plugin-solid"
import tailwindcss from "@tailwindcss/vite"
import { fileURLToPath } from "url"

const theme = fileURLToPath(new URL("./public/oc-theme-preload.js", import.meta.url))

const channel = (() => {
  const raw = process.env.OPENCODE_CHANNEL
  if (raw === "dev" || raw === "beta" || raw === "prod" || raw === "quantcode") return raw
  if (process.env.OPENCODE_CHANNEL === "latest") return "prod"
  // This fork is distributed as QuantCode. Keep the upstream channels
  // available when explicitly requested, but make an unqualified local
  // frontend start match the product users are actually running.
  return "quantcode"
})()
const productName = channel === "quantcode" ? "QuantCode" : "OpenCode"
const productIcon = channel === "quantcode" ? "/quantcode-icon.png" : "/favicon-96x96-v3.png"

/**
 * @type {import("vite").PluginOption}
 */
export default [
  {
    name: "opencode-desktop:config",
    config() {
      return {
        resolve: {
          alias: {
            "@": fileURLToPath(new URL("./src", import.meta.url)),
          },
        },
        define: {
          "import.meta.env.VITE_OPENCODE_CHANNEL": JSON.stringify(channel),
        },
        worker: {
          format: "es",
        },
      }
    },
  },
  {
    name: "opencode-desktop:theme-preload",
    transformIndexHtml(html) {
      let transformed = html.replace("<title>OpenCode</title>", `<title>${productName}</title>`)
      if (channel === "quantcode") {
        transformed = transformed
          .replace(
            /<link rel="icon" type="image\/png" href="(?:\.\/|\/)favicon-96x96-v3\.png" sizes="96x96" \/>/,
            `<link rel="icon" type="image/png" href="${productIcon}" sizes="96x96" />`,
          )
          .replace(
            /<link rel="icon" type="image\/svg\+xml" href="(?:\.\/|\/)favicon-v3\.svg" \/>/,
            `<link rel="icon" type="image/png" href="${productIcon}" />`,
          )
          .replace(
            /<link rel="shortcut icon" href="(?:\.\/|\/)favicon-v3\.ico" \/>/,
            `<link rel="shortcut icon" href="${productIcon}" />`,
          )
          .replace(
            /<link rel="apple-touch-icon" sizes="180x180" href="(?:\.\/|\/)apple-touch-icon-v3\.png" \/>/,
            `<link rel="apple-touch-icon" sizes="180x180" href="${productIcon}" />`,
          )
          .replace(/<meta property="(?:og|twitter):image" content="(?:\.\/|\/)social-share\.png" \/>/g, (tag) =>
            tag.replace(/content="[^"]+"/, `content="${productIcon}"`),
          )
          .replace("<body ", '<body data-product="quantcode" ')
      }
      return transformed.replace(
        /<script id="oc-theme-preload-script" src="(?:\.\/|\/)oc-theme-preload\.js"><\/script>/,
        `<script id="oc-theme-preload-script">${readFileSync(theme, "utf8")}</script>`,
      )
    },
  },
  tailwindcss(),
  solidPlugin(),
]
