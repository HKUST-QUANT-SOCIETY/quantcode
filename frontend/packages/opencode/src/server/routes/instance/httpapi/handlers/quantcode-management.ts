import { readFile, stat } from "node:fs/promises"

/** Host-owned gateway credential; never expose it in browser payloads or MCP. */
export async function quantcodeManagement(path: "/deployments" | "/deployments/cancel" | "/receipts/reconcile", sessionID: string, payload?: unknown): Promise<unknown> {
  const filename = process.env.QUANTCODE_IDENTITY_SESSION_FILE
  if (!filename) return { error: "Identity gateway session is not configured" }
  const info = await stat(filename)
  if (info.mode & 0o077 || (process.getuid && info.uid !== process.getuid())) throw new Error("Identity session file must be owned by this host account with permissions 0600")
  const record = JSON.parse(await readFile(filename, "utf8")) as { gateway: string; token: string }
  const base = new URL(record.gateway)
  if (base.protocol !== "https:" && !(base.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(base.hostname))) {
    throw new Error("Identity gateway requires HTTPS or loopback HTTP")
  }
  const identity = await fetch(new URL("/session", base), {
    headers: { Authorization: `Bearer ${record.token}` }, redirect: "error", signal: AbortSignal.timeout(10000),
  })
  if (!identity.ok) throw new Error("Gateway session is unavailable")
  const context = await identity.json() as { session_id?: string; role?: string }
  const allowed = context.role === "admin" || (path === "/receipts/reconcile" && context.role === "approver")
  if (!allowed || context.session_id !== sessionID) throw new Error("Management identity differs from the current workspace")
  const response = await fetch(new URL(path, base), {
    method: payload === undefined ? "GET" : "POST",
    headers: { Authorization: `Bearer ${record.token}`, "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    redirect: "error",
    signal: AbortSignal.timeout(15000),
  })
  if (!response.ok) return { error: `Management request rejected (${response.status})` }
  return response.json()
}
