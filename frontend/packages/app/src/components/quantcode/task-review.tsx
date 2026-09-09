import { For, Show, createEffect, createMemo, createUniqueId, on, onCleanup } from "solid-js"
import { createStore } from "solid-js/store"
import { Button } from "@opencode-ai/ui/button"
import type { QuantCodeReuseState, QuantCodeSolutionState, QuantCodeReceiptState, QuantCodeTaskLockState, QuantCodeBudgetState, QuantCodeBudgetReviewState } from "@opencode-ai/sdk/v2"
import { useSDK } from "@/context/sdk"
import { useSync } from "@/context/sync"
import "./task-review.css"
import { WriteReceiptReview, TaskLockRecovery } from "./write-receipt-review"
import { BudgetRequestReview } from "./budget-review"

/** Native task reviews never send approval text to the model. The server
 * checks the exact proposal/document revision again before recording it. */
export function QuantCodeTaskReview(props: { sessionID: string; expanded?: boolean }) {
  const sdk = useSDK()
  const sync = useSync()
  const id = createUniqueId()
  const [state, setState] = createStore({
    solution: undefined as QuantCodeSolutionState | undefined,
    reuse: undefined as QuantCodeReuseState | undefined,
    receipts: undefined as QuantCodeReceiptState | undefined,
    lock: undefined as QuantCodeTaskLockState | undefined,
    budget: undefined as QuantCodeBudgetState | undefined,
    budgetReview: undefined as QuantCodeBudgetReviewState | undefined,
    solutionNote: "", reuseNote: "", error: "", notice: "", loading: true,
    submitting: "" as "" | "solution" | "reuse" | "continue", resumed: false, open: props.expanded ?? false,
  })
  const document = createMemo(() => state.solution?.solution)
  const proposal = createMemo(() => state.reuse?.proposal)
  const waiting = createMemo(() => !!state.receipts?.unresolved.length || document()?.status === "draft" || (!!proposal() && proposal()!.coverage !== "full" && !state.reuse?.review))
  const busy = () => (sync().data.session_status[props.sessionID]?.type ?? "idle") !== "idle"
  const approved = () => document()?.status === "frozen" || state.reuse?.review?.decision === "approve"
  const canContinue = () => approved() && !waiting() && document()?.status !== "superseded"
    && state.reuse?.review?.decision !== "reject" && state.lock?.status === "idle"
    && state.budget?.status !== "stopped_budget" && state.budgetReview?.lock.status === "idle" && !busy()
  let refresh = async () => false
  let decide = async (_kind: "solution" | "reuse", _decision: "approve" | "reject") => {}
  let resume = async () => {}

  createEffect(on(() => [sdk(), props.sessionID] as const, ([context, sessionID]) => {
    const lifetime = new AbortController()
    let revision = 0
    let loading = false
    let pending = false
    let running = false
    let finished = false
    const active = () => !lifetime.signal.aborted && sdk() === context && props.sessionID === sessionID
    setState({ solution: undefined, reuse: undefined, receipts: undefined, lock: undefined, budget: undefined, budgetReview: undefined, solutionNote: "", reuseNote: "", error: "", notice: "", loading: true, submitting: "", resumed: false })
    const load = async (duringSubmit = false) => {
      if (loading || (pending && !duringSubmit) || !active()) return false
      loading = true
      const version = ++revision
      setState("loading", true)
      try {
        const options = { signal: lifetime.signal, throwOnError: false as const }
        const [solution, reuse, receipts, lock, budget] = await Promise.all([
          context.client.quantcode.solution.status({ sessionID }, options),
          context.client.quantcode.reuse.status({ sessionID }, options),
          context.client.quantcode.writeReceipt.status({ sessionID }, options),
          context.client.quantcode.taskLock.status({ sessionID }, options),
          context.client.quantcode.budget.reviewState({ sessionID }, options),
        ])
        if (!active() || revision !== version) return false
        if (solution.error || reuse.error || receipts.error || lock.error || budget.error || !solution.data || !reuse.data || !receipts.data || !lock.data || !budget.data) {
          throw new Error(solution.error?.message ?? reuse.error?.message ?? receipts.error?.message ?? lock.error?.message ?? budget.error?.message ?? "暂时无法读取任务方案，请确认登录与组织服务连接后重试。")
        }
        if (solution.data.session_id !== sessionID || reuse.data.session_id !== sessionID) throw new Error("任务已切换，请重新打开方案。")
        if (state.solution?.solution?.doc_hash !== solution.data.solution?.doc_hash || state.solution?.solution?.version !== solution.data.solution?.version) {
          setState("solutionNote", "")
        }
        if (state.reuse?.proposal?.proposal_hash !== reuse.data.proposal?.proposal_hash) setState("reuseNote", "")
        setState({ solution: solution.data, reuse: reuse.data, receipts: receipts.data, lock: lock.data, budget: budget.data.budget, budgetReview: budget.data, error: "" })
        return true
      } catch (error) {
        if (!lifetime.signal.aborted && revision === version) setState({ solution: undefined, reuse: undefined, receipts: undefined, lock: undefined, budget: undefined, budgetReview: undefined,
          error: error instanceof Error ? error.message : "读取失败，请重试。" })
        return false
      } finally {
        loading = false
        if (!lifetime.signal.aborted && revision === version) setState("loading", false)
      }
    }
    refresh = async () => {
      const loaded = await load()
      if (loaded && !busy() && state.lock?.status === "idle") setState("resumed", false)
      return loaded
    }
    resume = async () => {
      if (loading || pending || !active() || state.error || state.resumed || !canContinue()) return
      pending = true
      running = false
      finished = false
      setState({ submitting: "continue", error: "", notice: "" })
      try {
        if (!await load(true) || !active()) return
        if (!canContinue()) throw new Error("任务状态已变化，请核对当前方案与执行状态。")
        const options = { signal: lifetime.signal, throwOnError: false as const }
        const [session, status] = await Promise.all([
          context.client.session.get({ sessionID }, options),
          context.client.session.status({}, options),
        ])
        if (!active()) return
        if (session.error || !session.data || session.data.id !== sessionID || session.data.directory !== context.directory) {
          throw new Error("任务或工作区已变化，请回到原任务后再继续。")
        }
        if (status.error || !status.data) throw new Error("暂时无法确认任务是否空闲，请刷新后核对。")
        if ((status.data[sessionID]?.type ?? "idle") !== "idle" || busy()) throw new Error("任务正在执行，请等待当前执行结束。")
        const { agent, model } = session.data
        if (!agent || !model) throw new Error("任务尚未保存模型或 Agent，请先核对任务设置。")
        // Empty parts preserve the reviewed intent. Use the task's saved
        // selection, not an unsent change in the current composer.
        const result = await context.client.session.promptAsync({ sessionID, parts: [], agent,
          model: { providerID: model.providerID, modelID: model.id }, variant: model.variant,
        }, options)
        if (!active()) return
        if (result.error) throw new Error("继续请求未确认，请刷新并核对当前任务记录。")
        if (state.error) return
        setState({ resumed: !finished, notice: "已请求继续执行。" })
      } catch (error) {
        if (active()) setState("error", error instanceof Error ? error.message : "继续请求未确认，请刷新并核对当前任务记录。")
      } finally {
        pending = false
        if (active()) setState("submitting", "")
      }
    }
    decide = async (kind, decision) => {
      if (loading || pending || lifetime.signal.aborted) return
      const doc = state.solution?.solution
      const coverage = state.reuse?.proposal
      const note = (kind === "solution" ? state.solutionNote : state.reuseNote).trim()
      if (!note || (kind === "solution" ? doc?.status !== "draft" : !coverage || !!state.reuse?.review)) return
      pending = true
      setState({ submitting: kind, error: "", notice: "" })
      try {
        const options = { signal: lifetime.signal, throwOnError: false as const }
        const result = kind === "solution"
          ? await context.client.quantcode.solution.review({ sessionID, quantCodeSolutionReview: {
              expected_hash: doc!.doc_hash, expected_version: doc!.version, decision, note,
            } }, options)
          : await context.client.quantcode.reuse.review({ sessionID, quantCodeReuseReview: {
              proposal_hash: coverage!.proposal_hash, decision, note,
            } }, options)
        if (lifetime.signal.aborted) return
        if (result.error || !result.data) throw new Error(result.error?.message ?? "决定未保存，方案可能已变化。请重新查看当前版本后提交。")
        setState({ notice: decision === "approve" ? "确认已记录。" : "修改意见已记录，请在对话中继续讨论。", solutionNote: "", reuseNote: "", resumed: false })
      } catch (error) {
        if (!lifetime.signal.aborted) setState({ solution: undefined, reuse: undefined,
          error: error instanceof Error ? error.message : "提交未完成，请刷新后查看记录，避免重复提交。" })
      } finally {
        pending = false
        if (!lifetime.signal.aborted) {
          setState("submitting", "")
          // Only refresh after success. A failed submission retains its error
          // until the user explicitly reloads the current revision.
          if (!state.error) await load()
        }
      }
    }
    void load()
    let scheduled: ReturnType<typeof setTimeout> | undefined
    const changed = (id: string) => {
      if (id !== sessionID || scheduled) return
      scheduled = setTimeout(() => { scheduled = undefined; if (!state.error) void load() }, 200)
    }
    const unsubscribe = [
      context.event.on("quantcode.inspection", event => changed(event.properties.sessionID)),
      context.event.on("quantcode.coverage.proposed", event => changed(event.properties.sessionID)),
      context.event.on("quantcode.coverage.reviewed", event => changed(event.properties.sessionID)),
      context.event.on("quantcode.solution.changed", event => changed(event.properties.sessionID)),
      context.event.on("quantcode.write.started", event => changed(event.properties.source_session_id)),
      context.event.on("quantcode.write.completed", event => changed(event.properties.source_session_id)),
      context.event.on("quantcode.write.reconciled", event => changed(event.properties.source_session_id)),
      context.event.on("quantcode.budget.changed", event => { if (event.properties.sessionID === state.budget?.root_session_id) changed(sessionID) }),
      context.event.on("message.updated", event => { if (event.properties.info.role === "user") changed(event.properties.info.sessionID) }),
      context.event.on("session.status", event => {
        if (event.properties.sessionID !== sessionID) return
        if (event.properties.status.type !== "idle") running = true
        else if (running) {
          running = false
          finished = true
          if (state.resumed) { setState("resumed", false); changed(sessionID) }
        }
      }),
      context.event.on("session.error", event => {
        if (event.properties.sessionID !== sessionID || (!state.resumed && state.submitting !== "continue")) return
        setState({ error: "任务未能继续，请核对对话中的错误与当前方案后再操作。", notice: "" })
      }),
    ]
    // This is a read projection, not another task state machine. Polling also
    // catches reviews made in another window and login revocation.
    const timer = setInterval(() => { if (state.open && !window.document.hidden && !state.error) void load() }, 5000)
    const focus = () => { if (!state.error) void load() }
    window.addEventListener("focus", focus)
    onCleanup(() => { lifetime.abort(); clearInterval(timer); clearTimeout(scheduled); unsubscribe.forEach(stop => stop()); window.removeEventListener("focus", focus) })
  }))

  return <details class="qc-task-review" classList={{ "qc-task-review-panel": props.expanded }} open={state.open} onToggle={event => {
    setState("open", event.currentTarget.open)
    if (event.currentTarget.open) void refresh()
  }}>
    <summary>
      <strong>任务方案与能力复用</strong>
      <span class="qc-task-review-status" data-pending={waiting()}>
        {state.error ? "读取失败" : state.loading && !state.solution ? "正在读取…" : state.receipts?.unresolved.length ? "写入回执未完成" : waiting() ? "待你确认" : "查看当前方案"}
      </span>
    </summary>
    <div class="qc-task-review-body" aria-busy={state.loading || !!state.submitting}>
      <div class="qc-task-review-toolbar">
        <p>确认前请核对目标、改动文件和验收要求。内容变化后需要重新确认。</p>
        <Button size="small" variant="ghost" disabled={state.loading || !!state.submitting} onClick={() => void refresh()}>刷新</Button>
      </div>
      <Show when={state.error}><p class="qc-task-review-error" role="alert">{state.error}</p></Show>
      <Show when={state.notice}><p class="qc-task-review-notice" role="status">{state.notice}</p></Show>
      <Show when={approved()}><div class="qc-task-review-actions">
        <Button type="button" variant="primary" icon="arrow-right" disabled={state.loading || !!state.submitting || !!state.error || state.resumed || !canContinue()}
          onClick={() => void resume()}>{state.submitting === "continue" ? "正在提交…" : state.resumed ? "已请求继续" : busy() ? "任务执行中" : "继续执行"}</Button>
      </div></Show>
      <Show when={state.budget}>{budget => <section class="qc-task-budget" aria-label="任务树用量">
        <header><h3>任务用量</h3><span>{budget().status === "stopped_budget" ? "预算已耗尽" : budget().status === "warning" ? "接近预算上限" : "包含子任务与辅助请求"}</span></header>
        <p>已确认 {budget().used.toLocaleString()} tokens · 预留 {budget().reserved.toLocaleString()} tokens
          {budget().token_limit === null ? " · 未设总额上限" : ` · 总额 ${(budget().token_limit ?? 0).toLocaleString()} tokens`}</p>
        <Show when={budget().token_limit !== null}><progress max={budget().token_limit ?? 1}
          value={budget().used + budget().reserved} aria-label="已确认用量和预留额度占总预算" /></Show>
        <Show when={budget().unconfirmed_requests > 0}><p>{budget().unconfirmed_requests} 次请求正在执行或尚缺完整用量回执，预留额度暂不返还。</p></Show>
        <Show when={budget().unpriced_requests > 0}><p>部分请求没有有效价格，当前不展示完整费用总额。</p></Show>
        <p>预留按输入估计与输出上限计算，实际用量以供应商回执为准。</p>
        <For each={state.budgetReview?.requests}>{request => <BudgetRequestReview sessionID={props.sessionID} request={request} refresh={() => refresh()} />}</For>
      </section>}</Show>
      <Show when={state.budgetReview?.lock.status === "recovery_required" && state.budgetReview.lock}>{lock => <TaskLockRecovery sessionID={props.sessionID} lock={lock()} budget refresh={() => refresh()} />}</Show>
      <Show when={state.lock?.status === "recovery_required" && state.lock}>{lock => <TaskLockRecovery sessionID={props.sessionID} lock={lock()} refresh={() => refresh()} />}</Show>
      <Show when={state.lock?.status === "other_host"}><p role="status">此任务由另一宿主管理，请在原宿主核对执行状态。</p></Show>
      <For each={state.receipts?.unresolved}>{receipt => <WriteReceiptReview sessionID={props.sessionID} receipt={receipt} refresh={() => refresh()} />}</For>
      <Show when={state.solution && state.reuse}>
        <div class="qc-task-review-columns">
          <section aria-labelledby={`${id}-solution-title`}>
            <header><h3 id={`${id}-solution-title`}>实施方案</h3>
              <span>{document() ? `第 ${document()!.version} 版` : "尚无方案"}</span>
            </header>
            <Show when={document()} fallback={<p>{state.solution?.classification.solution_required
              ? "此任务需要先形成方案。请在对话中完善目标、文件范围与验收标准。"
              : "当前任务无需额外冻结方案，可按已有权限继续。"}</p>}>
              {doc => <>
                <p class="qc-task-review-goal">{doc().goal}</p>
                <p class="qc-task-review-phase">{doc().status === "frozen" ? "已确认" : doc().status === "draft" ? "等待确认" : "需要修订"}</p>
                <h4>验收要求</h4><ul><For each={doc().acceptance_criteria}>{item => <li>{item}</li>}</For></ul>
                <h4>改动文件</h4>
                <Show when={doc().file_impact.length} fallback={<p>当前方案未声明文件改动。</p>}>
                  <ul class="qc-task-review-files"><For each={doc().file_impact}>{file => <li><code>{file}</code></li>}</For></ul>
                </Show>
                <Show when={doc().rounds.length}><details class="qc-task-review-history"><summary>讨论与确认记录</summary>
                  <For each={doc().rounds}>{round => <div><p>{round.feedback}</p><small>{round.revision} {round.at}</small></div>}</For>
                </details></Show>
                <Show when={doc().status === "draft"}>
                  <form onSubmit={event => { event.preventDefault(); void decide("solution", "approve") }}>
                    <label for={`${id}-solution-note`}>确认说明或修改意见</label>
                    <textarea id={`${id}-solution-note`} required maxLength={4000} value={state.solutionNote}
                      onInput={event => setState("solutionNote", event.currentTarget.value)} disabled={!!state.submitting}
                      placeholder="说明你确认的范围，或需要调整的内容" />
                    <div class="qc-task-review-actions">
                      <Button type="button" variant="secondary" disabled={state.loading || !!state.submitting || !state.solutionNote.trim()}
                        onClick={() => void decide("solution", "reject")}>要求修改</Button>
                      <Button type="submit" variant="primary" disabled={state.loading || !!state.submitting || !state.solutionNote.trim()}>
                        {state.submitting === "solution" ? "正在保存…" : `确认第 ${doc().version} 版`}
                      </Button>
                    </div>
                  </form>
                </Show>
              </>}
            </Show>
          </section>
          <section aria-labelledby={`${id}-reuse-title`}>
            <header><h3 id={`${id}-reuse-title`}>能力覆盖</h3><span>{proposal() ? ({ full: "完整覆盖", partial: "部分覆盖", none: "暂无覆盖" }[proposal()!.coverage]) : "待评估"}</span></header>
            <ul class="qc-task-review-checks">
              <li>能力目录：{state.reuse?.catalog_checked ? "已检索" : "尚未取得有效结果"}</li>
              <li>组内 Memory：{state.reuse?.memory_checked ? "已检索" : "尚未取得有效结果"}</li>
            </ul>
            <Show when={proposal()} fallback={<p>任务需先查询能力目录和组内 Memory，再说明可复用组件与剩余缺口。</p>}>
              {coverage => <>
                <p class="qc-task-review-goal">{coverage().reason}</p>
                <Show when={coverage().components.length}><h4>复用组件</h4><ul><For each={coverage().components}>{name => <li><code>{name}</code></li>}</For></ul></Show>
                <Show when={state.reuse?.review} fallback={<>
                  <p>{coverage().coverage === "full" ? "已接通的对应组件可直接复用；新增实现仍需你确认处理方案。" : "请先决定是否按上述方案处理能力缺口，再继续写入。"}</p>
                  <details class="qc-task-review-history" open={coverage().coverage !== "full"}>
                  <summary>{coverage().coverage === "full" ? "需要新增实现时，确认处理方案" : "决定如何处理能力缺口"}</summary>
                  <form onSubmit={event => { event.preventDefault(); void decide("reuse", "approve") }}>
                    <label for={`${id}-reuse-note`}>缺口处理决定</label>
                    <textarea id={`${id}-reuse-note`} required maxLength={4000} value={state.reuseNote}
                      onInput={event => setState("reuseNote", event.currentTarget.value)} disabled={!!state.submitting}
                      placeholder="确认补充适配或自定义实现的范围，或说明需要重新讨论的内容" />
                    <div class="qc-task-review-actions">
                      <Button type="button" variant="secondary" disabled={state.loading || !!state.submitting || !state.reuseNote.trim()}
                        onClick={() => void decide("reuse", "reject")}>重新讨论</Button>
                      <Button type="submit" variant="primary" disabled={state.loading || !!state.submitting || !state.reuseNote.trim()}>
                        {state.submitting === "reuse" ? "正在保存…" : "确认处理方案"}
                      </Button>
                    </div>
                  </form>
                  </details>
                </>}>
                  {review => <div class="qc-task-review-decision"><strong>{review().decision === "approve" ? "已确认处理方案" : "已要求重新讨论"}</strong><p>{review().note}</p></div>}
                </Show>
              </>}
            </Show>
          </section>
        </div>
      </Show>
    </div>
  </details>
}
