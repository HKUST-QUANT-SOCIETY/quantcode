/** Explicit host-only import of one URL/API-key connection; never autoloaded. */
import path from "node:path"
import { parse, modify, applyEdits, type ParseError } from "jsonc-parser"
import { Global } from "@opencode-ai/core/global"
import { Config } from "../src/config/config"
import { QuantCodeConfigPolicy } from "../src/quantcode/config-policy"
import { QuantCodeIdentity } from "../src/quantcode/identity"
import { readPrivateFile } from "../src/quantcode/private-file"
import { digest, readCurrent, updateHostFile } from "./quantcode-host-file"

const [action, configFile, authFile, providerID, expected] = process.argv.slice(2)
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected an object")
  return value as Record<string, unknown>
}
function jsonc(raw: string) {
  const errors: ParseError[] = []
  const value: unknown = parse(raw, errors, { allowTrailingComma: true })
  if (errors.length) throw new Error("Invalid configuration JSON")
  return object(value)
}
async function main() {
  if (process.env.OPENCODE_CHANNEL !== "quantcode" || !["preview", "import"].includes(action) ||
      !configFile || !authFile || !path.isAbsolute(configFile) || !path.isAbsolute(authFile) ||
      !providerID || !QuantCodeConfigPolicy.validProviderID(providerID)) throw new Error("Invalid import arguments")
  const sourceConfig = await readPrivateFile(configFile, 2_000_000)
  const sourceAuth = await readPrivateFile(authFile, 262144)
  const connection = QuantCodeConfigPolicy.connection(object(jsonc(sourceConfig).provider)[providerID])
  const credential = object(object(JSON.parse(sourceAuth))[providerID])
  if (!connection || credential.type !== "api" || typeof credential.key !== "string" || !credential.key.trim() ||
      credential.key.length > 16384 || /\{(?:env|file):|\$\{/i.test(credential.key)) throw new Error("Selected connection is not a supported URL/API-key provider")
  if (credential.metadata !== undefined && !QuantCodeConfigPolicy.credentialMatches({ type: "api",
      metadata: object(credential.metadata) as Record<string, string> }, connection.options.baseURL)) {
    throw new Error("The source credential is bound to another endpoint; complete or repair the source connection before import")
  }
  const destination = Config.globalConfigFile()
  const authDestination = path.join(Global.Path.data, "auth.json")
  if ([destination, authDestination].includes(configFile) || [destination, authDestination].includes(authFile))
    throw new Error("Source and QuantCode destination must be different")
  const before = await readCurrent(destination, 2_000_000)
  const beforeAuth = await readCurrent(authDestination, 262144)
  const current = before ? jsonc(before) : {}
  const currentAuth = beforeAuth ? object(JSON.parse(beforeAuth)) : {}
  const providers = current.provider === undefined ? {} : object(current.provider)
  // Never replace another configured provider or import an upstream account.
  if (Object.hasOwn(providers, providerID) || Object.hasOwn(currentAuth, providerID)) throw new Error("Provider already exists; use QuantCode settings to edit it")
  const snapshot = digest(JSON.stringify({ sourceConfig: digest(sourceConfig), sourceAuth: digest(sourceAuth), providerID,
    destination, before: before === undefined ? "absent" : digest(before), authDestination,
    beforeAuth: beforeAuth === undefined ? "absent" : digest(beforeAuth) }))
  if (action === "preview") {
    process.stdout.write(JSON.stringify({ provider: providerID, name: connection.name, url: connection.options.baseURL,
      models: Object.keys(connection.models), credential: "api_key_present", expected_digest: snapshot }) + "\n")
    return
  }
  if (expected !== snapshot) throw new Error("Import preview changed")
  const identity = await QuantCodeIdentity.currentIdentity()
  const revalidate = async () => {
    if (await readPrivateFile(configFile, 2_000_000) !== sourceConfig || await readPrivateFile(authFile, 262144) !== sourceAuth ||
        (await QuantCodeIdentity.currentIdentity()).session_id !== identity.session_id) throw new Error("Import identity or source changed")
  }
  // Two existing stores are written in dependency order. If configuration
  // publication fails, the unused credential is retained for explicit repair;
  // never roll back a potentially newer setting written by another process.
  await updateHostFile({ filename: authDestination, expected: beforeAuth === undefined ? "absent" : digest(beforeAuth),
    maxBytes: 262144, history: "model-import-history", update: async () => {
      await revalidate()
      return JSON.stringify({ ...currentAuth, [providerID]: { type: "api", key: credential.key,
        metadata: { quantcode_base_url: QuantCodeConfigPolicy.modelURL(connection.options.baseURL) } } }, null, 2) + "\n"
    } })
  await updateHostFile({ filename: destination, expected: before === undefined ? "absent" : digest(before),
    maxBytes: 2_000_000, history: "model-import-history", update: async () => {
      await revalidate()
      return applyEdits(before ?? "{}", modify(before ?? "{}", ["provider", providerID], connection,
        { formattingOptions: { insertSpaces: true, tabSize: 2 } }))
    } })
  process.stdout.write(JSON.stringify({ imported: true, provider: providerID, source_preserved: true }) + "\n")
}
main().catch(() => {
  // Parser errors and SDK causes may quote the input. Never log source keys.
  process.stderr.write("Model import did not finish. Check private paths, compatible provider, preview digest and destination conflicts. If only the credential was saved, complete this connection in QuantCode model settings.\n")
  process.exitCode = 1
})
