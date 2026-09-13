import type { QuantCodeServerAdminSession } from "../../identity"

/** All administrator features use the same server-verified organization role. */
export function workspaceAccount(input: {
  view: string
  organizationStatus: "loading" | "ready" | "error"
  actor: string
  role: string
  verificationPending?: boolean
  operations?: QuantCodeServerAdminSession
}, now = Date.now()) {
  const organizationReady = input.organizationStatus === "ready"
  const administrator = organizationReady && input.role === "admin"
  const operationsConnected = administrator && !!input.operations && Date.parse(input.operations.expires_at) > now
  return {
    organizationReady,
    administrator,
    operationsConnected,
    operationsContext: operationsConnected && input.view === "server-admin",
    label: organizationReady ? input.actor : input.verificationPending ? '身份待核验' : "重新登录",
    showLoginNotice: !organizationReady,
    organizationLabel: organizationReady ? input.actor : input.verificationPending ? '暂时无法核验身份' : "尚未登录",
  }
}
