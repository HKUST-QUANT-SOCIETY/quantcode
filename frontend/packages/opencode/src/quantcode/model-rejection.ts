import { APICallError } from "ai"

/** Only the host-pinned organization gateway can attest that a reservation
 * never reached the provider. Transport errors and upstream 429s stay unknown. */
export function unexecutedUsage(error: unknown, requestID: string, gateway = process.env.QUANTCODE_MODEL_GATEWAY_URL) {
  if (!gateway || !APICallError.isInstance(error) || error.statusCode !== 429) return
  if (error.url !== gateway.replace(/\/$/, "") + "/chat/completions") return
  if (error.responseHeaders?.["x-quantcode-request-id"] !== requestID ||
      error.responseHeaders?.["x-quantcode-request-status"] !== "not-started") return
  return { input: 0, output: 0, total: 0, cost: 0 }
}
