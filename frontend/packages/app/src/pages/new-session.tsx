import { Show, createEffect, createMemo, createResource, onCleanup, untrack } from "solid-js"
import { createStore } from "solid-js/store"
import { useNavigate, useSearchParams } from "@solidjs/router"
import { base64Encode } from "@opencode-ai/core/util/encode"
import { Button } from "@opencode-ai/ui/button"
import { NewSessionDesignView } from "@/components/session"
import { PromptInput } from "@/components/prompt-input"
import { useSettingsCommand } from "@/components/settings-dialog"
import {
  PromptProjectAddButton,
  PromptProjectSelector,
  createPromptProjectController,
} from "@/components/prompt-project-selector"
import { useComments } from "@/context/comments"
import { usePrompt } from "@/context/prompt"
import { useSDK } from "@/context/sdk"
import { useSync } from "@/context/sync"
import { useServerSync } from "@/context/server-sync"
import { useLanguage } from "@/context/language"
import { createPromptInputController, createPromptProjectControls } from "@/pages/session/composer"
import { useSessionKey } from "@/pages/session/session-layout"
import { useComposerCommands } from "@/pages/session/use-composer-commands"
import { NEW_SESSION_CONTENT_WIDTH } from "@/pages/session/new-session-layout"
import { PromptWorkspaceSelector } from "@/components/prompt-workspace-selector"
import { isQuantCode } from "@/brand"
import { useTabs } from "@/context/tabs"
import { useLocal } from "@/context/local"
import { prepareResearchWorkspace } from "@/components/quantcode/workspaces"

const showWorkspaceBar = import.meta.env.VITE_OPENCODE_CHANNEL !== "prod"

/**
 * The `/new-session` draft page. Unlike `session.tsx`, this only renders the prompt
 * composer for a brand-new session — no terminal, review pane, file tree, or message
 * timeline. Submitting promotes the draft into a real session (see prompt-input/submit).
 */
export default function NewSessionPage() {
  const prompt = usePrompt()
  const tabs = useTabs()
  const local = useLocal()
  const navigate = useNavigate()
  const sdk = useSDK()
  const sync = useSync()
  const serverSync = useServerSync()
  const comments = useComments()
  const language = useLanguage()
  const route = useSessionKey()
  const [searchParams, setSearchParams] = useSearchParams<{ draftId?: string; prompt?: string; submit?: string }>()
  const [runtime] = createResource(() => isQuantCode ? sdk().client : undefined,
    client => client.experimental.capabilities.get().then(result => result.error ? undefined : result.data).catch(() => undefined))
  const allowWorktrees = () => !isQuantCode || runtime()?.quantcodeUnifiedRuntime === false

  useComposerCommands()
  useSettingsCommand()

  let inputRef: HTMLDivElement | undefined

  const inputController = createPromptInputController({
    sessionKey: route.sessionKey,
    sessionID: () => route.params.id,
    queryOptions: serverSync().queryOptions,
  })
  const projectControls = createPromptProjectControls()
  const projectController = createPromptProjectController({
    controls: projectControls,
    onDone: () => inputRef?.focus(),
  })

  const [store, setStore] = createStore({
    worktree: undefined as string | undefined,
    autoSubmit: false,
    autoSubmitStarted: false,
    title: "",
    creating: false,
    error: "",
  })
  let alive = true
  onCleanup(() => { alive = false })
  const createTask = async (event: SubmitEvent) => {
    event.preventDefault()
    if (store.creating || !store.title.trim() || !prompt.ready()) return
    const target = sdk()
    const draftID = searchParams.draftId
    const current = () => alive && sdk() === target && searchParams.draftId === draftID
    setStore({ creating: true, error: "" })
    try {
      const workspace = await prepareResearchWorkspace(target.client, { preferred: target.directory, current })
      const directory = await workspace.validate(target.directory)
      const response = await target.client.session.create({ directory, title: store.title.trim() }, { throwOnError: true })
      if (!response.data) throw new Error("未收到任务创建结果，请先在任务列表中检查。")
      if (!current()) return
      const session = response.data
      // Carry an older unsent draft forward without executing it. This creates
      // only the native session; all following messages use that same session.
      const next = prompt.capture({ dir: base64Encode(directory), id: session.id })
      next.set(prompt.current(), prompt.cursor())
      prompt.context.items().forEach(next.context.add)
      local.session.promote(directory, session.id)
      if (draftID) tabs.promoteDraft(draftID, { server: tabs.draft(draftID).server, sessionId: session.id })
      else navigate(`/${base64Encode(directory)}/session/${session.id}`)
    } catch (error) {
      if (current()) setStore("error", error instanceof Error ? error.message : "任务创建失败，请重试。")
    } finally {
      if (current()) setStore("creating", false)
    }
  }

  const submitWhenReady = () => {
    const controls = inputController()
    if (!store.autoSubmit || store.autoSubmitStarted || !inputRef) return
    if (controls.model.loading || controls.agents.loading) return
    if (!controls.model.selection.current() || !controls.agents.current) return

    const form = inputRef.closest<HTMLFormElement>("form[data-component=\"session-new-composer\"]")
    if (!form) return

    setStore("autoSubmitStarted", true)
    setSearchParams({ ...searchParams, prompt: undefined, submit: undefined })
    requestAnimationFrame(() => form.requestSubmit())
  }

  const newSessionWorktree = createMemo(() => {
    if (!allowWorktrees()) return sdk().directory
    if (store.worktree) return store.worktree
    const project = sync().project
    if (project && sdk().directory !== project.worktree) return sdk().directory
    return "main"
  })
  const projectRoot = createMemo(() => sync().project?.worktree ?? sdk().directory)
  const localBranch = createMemo(() => serverSync().child(projectRoot())[0].vcs?.branch)
  const selectedBranch = createMemo(() => {
    const worktree = newSessionWorktree()
    if (worktree === "main" || worktree === "create") return localBranch()
    return serverSync().child(worktree)[0].vcs?.branch ?? localBranch()
  })

  createEffect(() => {
    if (!prompt.ready()) return
    untrack(() => {
      const text = searchParams.prompt
      if (!text) return
      prompt.set([{ type: "text", content: text, start: 0, end: text.length }], text.length)
      setStore("autoSubmit", !isQuantCode && searchParams.submit === "true")
      setSearchParams({ ...searchParams, prompt: undefined })
    })
  })

  createEffect(() => {
    inputController()
    store.autoSubmit
    untrack(submitWhenReady)
  })

  createEffect(() => {
    if (!prompt.ready()) return
    requestAnimationFrame(() => inputRef?.focus())
  })
  const ready = Promise.resolve()
  const [promptReady] = createResource(
    () => prompt.ready.promise ?? ready,
    (promise) => promise.then(() => true),
  )

  return (
    <div class="relative size-full overflow-hidden flex flex-col">
      <div class="flex-1 min-h-0 flex flex-col gap-2 p-2">
        <div class="@container relative flex flex-col min-h-0 h-full bg-background-stronger flex-1">
          <div class="flex-1 min-h-0 overflow-hidden rounded-[10px]">
            <NewSessionDesignView>
              <div class={NEW_SESSION_CONTENT_WIDTH}>
                <Show
                  when={prompt.ready() || promptReady()}
                  fallback={
                    <div class="w-full min-h-32 md:min-h-40 rounded-md border border-border-weak-base bg-background-base/50 px-4 py-3 text-text-weak pointer-events-none">
                      {language.t("prompt.loading")}
                    </div>
                  }
                >
                  <div class="flex flex-col" classList={{ "gap-8": showWorkspaceBar, "gap-3": !showWorkspaceBar }}>
                    <Show when={!isQuantCode} fallback={
                      <form onSubmit={createTask} class="flex flex-col gap-5 rounded-xl border border-border-weak-base p-6" aria-label="新建任务">
                        <p class="text-text-weak">先确定任务和工作目录，再开始对话。</p>
                        <label class="flex flex-col gap-2">任务名称<input autofocus required maxLength={160} disabled={store.creating} value={store.title} onInput={event => setStore("title", event.currentTarget.value)} placeholder="例如：因子复核" class="rounded-md border border-border-weak-base bg-background-base px-3 py-2" /></label>
                        <div class="flex flex-col gap-2"><span>工作目录</span><code class="break-all rounded-md bg-background-base p-3">{sdk().directory}</code><p class="text-sm text-text-weak">文件读写和命令都在此目录执行。可以通过下方项目选择器更换目录。</p></div>
                        <Show when={store.error}><p role="alert" class="text-text-critical-base">{store.error}</p></Show>
                        <Button type="submit" variant="primary" disabled={store.creating || !store.title.trim()} class="self-start">{store.creating ? "正在创建…" : "创建任务并进入对话"}</Button>
                      </form>
                    }>
                    <PromptInput
                      controls={inputController()}
                      variant="new-session"
                      ref={(el) => {
                        inputRef = el
                        submitWhenReady()
                      }}
                      newSessionWorktree={newSessionWorktree()}
                      onNewSessionWorktreeReset={() => setStore("worktree", undefined)}
                      onSubmit={() => comments.clear()}
                      toolbar={
                        <Show when={!projectController.selected()}>
                          <PromptProjectAddButton controller={projectController} />
                        </Show>
                      }
                    />
                    </Show>
                    <Show when={projectController.selected()}>
                      <div
                        class="flex min-h-7 min-w-0 items-center gap-0 text-v2-text-text-faint"
                        classList={{
                          "flex-col justify-center sm:flex-row": showWorkspaceBar,
                          "justify-start": !showWorkspaceBar,
                        }}
                      >
                        <PromptProjectSelector
                          controller={projectController}
                          placement={showWorkspaceBar ? "bottom" : "bottom-start"}
                        />
                        <Show when={showWorkspaceBar}>
                          <PromptWorkspaceSelector
                            value={newSessionWorktree()}
                            projectRoot={projectRoot()}
                            workspaces={sync().project?.sandboxes ?? []}
                            branch={selectedBranch()}
                            allowWorktrees={allowWorktrees()}
                            onChange={(value) =>
                              setStore(
                                "worktree",
                                value === "main" && sync().project?.worktree !== sdk().directory
                                  ? sync().project?.worktree
                                  : value,
                              )
                            }
                            onDone={() => inputRef?.focus()}
                          />
                        </Show>
                      </div>
                    </Show>
                  </div>
                </Show>
              </div>
            </NewSessionDesignView>
          </div>
        </div>
      </div>
    </div>
  )
}
