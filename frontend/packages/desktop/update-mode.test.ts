import { describe, expect, test } from "bun:test"
import { isQuantCodeUpdaterEnabled, resolveQuantCodeUpdateFeed, resolveQuantCodeUpdateMode } from "./update-mode"

const empty = {}

describe("QuantCode updater trust mode", () => {
  test("keeps the anonymous feed disabled by default", () => {
    expect(resolveQuantCodeUpdateFeed(empty)).toBe("disabled")
    expect(resolveQuantCodeUpdateFeed({ QUANTCODE_UPDATE_FEED: "disabled", QUANTCODE_PUBLIC_RELEASES: "true" })).toBe(
      "disabled",
    )
  })

  test("allows an explicitly public feed without carrying credentials", () => {
    expect(resolveQuantCodeUpdateFeed({ QUANTCODE_UPDATE_FEED: "public" })).toBe("public")
    expect(resolveQuantCodeUpdateFeed({ QUANTCODE_PUBLIC_RELEASES: "true" })).toBe("public")
  })

  test("keeps update trust separate from feed availability", () => {
    expect(resolveQuantCodeUpdateMode({ QUANTCODE_SIGNED_RELEASE: "true" }, "darwin")).toBe("signed")
    expect(resolveQuantCodeUpdateFeed({ QUANTCODE_SIGNED_RELEASE: "true" })).toBe("disabled")
  })

  test("enables updates only when both policy inputs are satisfied", () => {
    expect(isQuantCodeUpdaterEnabled("unsigned", "public")).toBe(false)
    expect(isQuantCodeUpdaterEnabled("signed", "disabled")).toBe(false)
    expect(isQuantCodeUpdaterEnabled("signed", "public")).toBe(true)
  })

  test("requires an explicit opt-in for unsigned local updates", () => {
    expect(resolveQuantCodeUpdateMode(empty, "darwin")).toBe("disabled")
    expect(resolveQuantCodeUpdateMode({ QUANTCODE_UNSIGNED_BUILD: "true" }, "darwin")).toBe("unsigned")
  })

  test("selects signed mode from an explicit release flag", () => {
    expect(resolveQuantCodeUpdateMode({ QUANTCODE_SIGNED_RELEASE: "true" }, "win32")).toBe("signed")
  })

  test("does not infer signed updater trust on Linux", () => {
    expect(resolveQuantCodeUpdateMode(empty, "linux")).toBe("disabled")
    expect(resolveQuantCodeUpdateMode({ QUANTCODE_SIGNED_RELEASE: "true" }, "linux")).toBe("disabled")
    expect(resolveQuantCodeUpdateMode({ QUANTCODE_UNSIGNED_BUILD: "true" }, "linux")).toBe("unsigned")
  })

  test("selects signed mode from complete platform credentials", () => {
    expect(
      resolveQuantCodeUpdateMode(
        {
          APPLE_CERTIFICATE: "p12",
          APPLE_CERTIFICATE_PASSWORD: "password",
          APPLE_API_KEY_CONTENT: "p8",
          APPLE_API_KEY_ID: "key-id",
          APPLE_API_ISSUER: "issuer",
        },
        "darwin",
      ),
    ).toBe("signed")
    expect(
      resolveQuantCodeUpdateMode(
        {
          AZURE_CLIENT_ID: "client",
          AZURE_TENANT_ID: "tenant",
          AZURE_SUBSCRIPTION_ID: "subscription",
          AZURE_TRUSTED_SIGNING_ACCOUNT_NAME: "account",
          AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: "profile",
          AZURE_TRUSTED_SIGNING_ENDPOINT: "https://example.test",
          AZURE_TRUSTED_SIGNING_PUBLISHER_NAME: "CN=HKUST Quant Society, O=HKUST, C=HK",
        },
        "win32",
      ),
    ).toBe("signed")
  })

  test("requires the Windows publisher subject for automatic signed mode", () => {
    expect(
      resolveQuantCodeUpdateMode(
        {
          AZURE_CLIENT_ID: "client",
          AZURE_TENANT_ID: "tenant",
          AZURE_SUBSCRIPTION_ID: "subscription",
          AZURE_TRUSTED_SIGNING_ACCOUNT_NAME: "account",
          AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: "profile",
          AZURE_TRUSTED_SIGNING_ENDPOINT: "https://example.test",
        },
        "win32",
      ),
    ).toBe("disabled")
  })

  test("credentials take precedence over the unsigned fallback", () => {
    expect(
      resolveQuantCodeUpdateMode(
        {
          QUANTCODE_UNSIGNED_BUILD: "true",
          AZURE_CLIENT_ID: "client",
          AZURE_TENANT_ID: "tenant",
          AZURE_SUBSCRIPTION_ID: "subscription",
          AZURE_TRUSTED_SIGNING_ACCOUNT_NAME: "account",
          AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE: "profile",
          AZURE_TRUSTED_SIGNING_ENDPOINT: "https://example.test",
          AZURE_TRUSTED_SIGNING_PUBLISHER_NAME: "CN=HKUST Quant Society, O=HKUST, C=HK",
        },
        "win32",
      ),
    ).toBe("signed")
  })
})
