import { expect, test } from "bun:test"
import { QuantCodeConfigPolicy } from "../../src/quantcode/config-policy"

test("a saved API credential cannot be paired with a different model URL or API path", () => {
  const credential = { type: "api", metadata: { quantcode_base_url: "https://model.example/v1" } }
  expect(QuantCodeConfigPolicy.credentialMatches(credential, "https://MODEL.example:443/v1/")).toBe(true)
  expect(QuantCodeConfigPolicy.credentialMatches(credential, "https://model.example/v1//")).toBe(false)
  expect(QuantCodeConfigPolicy.credentialMatches(credential, "https://other.example/v1")).toBe(false)
  expect(QuantCodeConfigPolicy.credentialMatches(credential, "https://model.example/another-tenant/v1")).toBe(false)
  expect(QuantCodeConfigPolicy.credentialMatches(credential, "https://user:secret@model.example/v1")).toBe(false)
  expect(QuantCodeConfigPolicy.credentialMatches({ type: "api" }, "https://model.example/v1")).toBe(false)
  expect(QuantCodeConfigPolicy.credentialMatches({ ...credential, metadata: { ...credential.metadata, injected: "option" } }, "https://model.example/v1")).toBe(false)
})
