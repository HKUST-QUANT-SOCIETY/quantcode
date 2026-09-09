import { describe, expect, test } from "bun:test"
import { QuantCodeIdentity } from "../../src/quantcode/identity"

// Isolated owner/metadata boundaries only. Gateway authentication, revocation,
// HTTP routes and SSE isolation require their own final integration checks.
const identity: QuantCodeIdentity.Identity = {
  session_id: "roster-login-1",
  actor_id: "researcher-one",
  group: "factor",
  role: "analyst",
  workspace_id: "workspace-one",
  workspace_path: "/research/workspace-one",
  github_subject: "github:researcher-one",
  resource_scopes: ["workspace:write", "workspace:read"],
  authorized_groups: ["factor"],
  issued_at: "2026-09-08T00:00:00Z",
  expires_at: "2026-09-09T00:00:00Z",
  identity_source: "ssh_roster",
}

describe("QuantCode native session ownership", () => {
  test("snapshots owner scopes without retaining login metadata or mutable scope arrays", () => {
    const current = { ...identity, resource_scopes: [...identity.resource_scopes] }
    const binding = QuantCodeIdentity.bindSession(current, "root-session")
    current.resource_scopes.push("production:deploy")

    expect(binding.owner.resource_scopes).toEqual(["workspace:read", "workspace:write"])
    expect(binding.owner).not.toHaveProperty("session_id")
    expect(binding.owner).not.toHaveProperty("expires_at")
    expect(binding.root_session_id).toBe("root-session")
    expect(binding.parent_session_id).toBeUndefined()
  })

  test("allows an authority-revalidated login with the same owner and equivalent scope set", () => {
    const binding = QuantCodeIdentity.bindSession(identity, "root-session")
    const current = {
      ...identity,
      session_id: "roster-login-2",
      resource_scopes: ["workspace:read", "workspace:write", "workspace:read"],
    }

    expect(QuantCodeIdentity.requireOwner({ quantcode: binding }, current)).toEqual(binding)
  })

  const changes: Array<[string, Partial<QuantCodeIdentity.Identity>]> = [
    ["actor", { actor_id: "researcher-two" }],
    ["group", { group: "model" }],
    ["role, including admin", { role: "admin" }],
    ["workspace id", { workspace_id: "workspace-two" }],
    ["workspace path", { workspace_path: "/research/workspace-two" }],
    ["GitHub subject", { github_subject: null }],
    ["revoked scope", { resource_scopes: ["workspace:read"] }],
    ["added scope", { resource_scopes: [...identity.resource_scopes, "production:deploy"] }],
  ]

  test.each(changes)("rejects a changed %s before continuation or child creation", (_, change) => {
    const metadata = { quantcode: QuantCodeIdentity.bindSession(identity, "root-session") }
    const current = { ...identity, ...change }

    expect(() => QuantCodeIdentity.requireOwner(metadata, current)).toThrow(QuantCodeIdentity.IdentityError)
    expect(() => QuantCodeIdentity.bindSession(current, "child-session", { id: "root-session", metadata })).toThrow(
      QuantCodeIdentity.IdentityError,
    )
  })

  test("inherits the original root through multiple child generations", () => {
    const root = QuantCodeIdentity.bindSession(identity, "root-session")
    const child = QuantCodeIdentity.bindSession(identity, "child-session", {
      id: "root-session",
      metadata: { quantcode: root },
    })
    const grandchild = QuantCodeIdentity.bindSession(identity, "grandchild-session", {
      id: "child-session",
      metadata: { quantcode: child },
    })

    expect(grandchild.root_session_id).toBe("root-session")
    expect(grandchild.parent_session_id).toBe("child-session")
    expect(grandchild.owner).toEqual(root.owner)
  })

  test("rejects legacy and malformed bindings rather than adopting caller ownership", () => {
    const binding = QuantCodeIdentity.bindSession(identity, "root-session")
    const invalid = [
      undefined,
      {},
      { quantcode: { ...binding, engine: "legacy-python" } },
      { quantcode: { ...binding, version: 2 } },
      { quantcode: { ...binding, root_session_id: "" } },
      { quantcode: { ...binding, owner: { actor_id: identity.actor_id } } },
    ]

    for (const metadata of invalid) {
      expect(QuantCodeIdentity.sessionBinding(metadata)).toBeUndefined()
      expect(() => QuantCodeIdentity.requireOwner(metadata, identity)).toThrow(QuantCodeIdentity.IdentityError)
    }
  })
})

describe("QuantCode caller metadata", () => {
  test("strips a forged binding on an unbound record", () => {
    const incoming = { label: "Research", quantcode: QuantCodeIdentity.bindSession(identity, "forged-session") }

    expect(QuantCodeIdentity.preserveBinding(undefined, incoming)).toEqual({ label: "Research" })
    expect(incoming).toHaveProperty("quantcode")
  })

  test("preserves the host binding while accepting descriptive updates", () => {
    const current = { label: "Before", quantcode: QuantCodeIdentity.bindSession(identity, "root-session") }
    const incoming = {
      label: "After",
      quantcode: QuantCodeIdentity.bindSession({ ...identity, actor_id: "researcher-two" }, "forged-session"),
    }
    const updated = QuantCodeIdentity.preserveBinding(current, incoming)

    expect(updated).toEqual({ label: "After", quantcode: current.quantcode })
    expect(current.label).toBe("Before")
    expect(incoming.quantcode.owner.actor_id).toBe("researcher-two")
    expect(QuantCodeIdentity.requireOwner(updated, identity).root_session_id).toBe("root-session")
  })

  test("keeps the binding when the caller omits or clears metadata", () => {
    const current = { quantcode: QuantCodeIdentity.bindSession(identity, "root-session") }

    expect(QuantCodeIdentity.preserveBinding(current)).toEqual(current)
    expect(QuantCodeIdentity.preserveBinding(current, { quantcode: null })).toEqual(current)
  })
})
