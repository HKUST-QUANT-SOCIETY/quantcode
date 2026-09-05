/**
 * QuantCode trace 桥 — session-ui → app 的极简模块级回调桥。
 *
 * 依赖方向约束：packages/app 依赖 packages/session-ui（反向不行），
 * 所以 run_agent 工具渲染处通过本桥把结果推给 app 侧的 QuantCode 面板。
 * app 侧（panels.tsx）在 onMount 注册 listener，onCleanup 注销。
 */

export type QuantCodeTracePayload = {
  status: string
  result: unknown
  sessionId?: string
}

type QuantCodeTraceListener = (payload: QuantCodeTracePayload) => void

let listener: QuantCodeTraceListener | null = null

export function setQuantCodeTraceListener(fn: QuantCodeTraceListener | null) {
  listener = fn
}

export function notifyQuantCodeTrace(payload: QuantCodeTracePayload) {
  listener?.(payload)
}
