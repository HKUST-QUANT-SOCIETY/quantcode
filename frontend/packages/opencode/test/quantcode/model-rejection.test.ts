import { describe, expect, test } from "bun:test"
import { APICallError } from "ai"
import { unexecutedUsage } from "../../src/quantcode/model-rejection"

const gateway = "http://127.0.0.1:6202/v1"
const requestID = "ea8f54b0-641c-4938-8ab4-3690b5cd0ad2"
const rejected = (changes: Partial<ConstructorParameters<typeof APICallError>[0]> = {}) => new APICallError({
  message: "Too Many Requests", url: gateway + "/chat/completions", requestBodyValues: {}, statusCode: 429,
  responseHeaders: { "x-quantcode-request-id": requestID, "x-quantcode-request-status": "not-started" }, ...changes,
})

describe("organization gateway rejection accounting", () => {
  test("releases only a receipt bound to this request from the pinned gateway", () => {
    expect(unexecutedUsage(rejected(), requestID, gateway)).toEqual({ input: 0, output: 0, total: 0, cost: 0 })
    expect(unexecutedUsage(rejected(), requestID, gateway + "/")).toEqual({ input: 0, output: 0, total: 0, cost: 0 })
  })
  test("unknown spend stays held for transport failure, upstream rejection or forged receipts", () => {
    for (const error of [new Error("Connection reset"), rejected({ responseHeaders: {} }),
      rejected({ url: "https://untrusted.example/v1/chat/completions" }), rejected({ statusCode: 502 }),
      rejected({ responseHeaders: { "x-quantcode-request-id": "another-request", "x-quantcode-request-status": "not-started" } }),
      rejected({ responseHeaders: { "x-quantcode-request-id": requestID } }),
    ]) expect(unexecutedUsage(error, requestID, gateway)).toBeUndefined()
    expect(unexecutedUsage(rejected(), requestID, "")).toBeUndefined()
  })
})
