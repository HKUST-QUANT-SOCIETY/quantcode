export type QuantCodeRole = "approver" | "analyst" | "admin"

/** Only values issued by the server Session Context are authoritative. */
export function resolveRole(value: unknown): QuantCodeRole {
  if (value === "admin" || value === "approver" || value === "analyst") return value
  return "analyst"
}

/** Admin visibility must compare the server-issued role, never an identity label. */
export function isAdminRole(value: unknown): boolean {
  return value === "admin"
}
