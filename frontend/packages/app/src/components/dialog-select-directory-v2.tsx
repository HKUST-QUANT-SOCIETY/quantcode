import "@pierre/trees/web-components"
import { FileTree } from "@pierre/trees"
import { Dialog, DialogBody, DialogFooter, DialogHeader, DialogTitle } from "@opencode-ai/ui/v2/dialog-v2"
import { ButtonV2 } from "@opencode-ai/ui/v2/button-v2"
import { TextInputV2 } from "@opencode-ai/ui/v2/text-input-v2"
import { useDialog } from "@opencode-ai/ui/context/dialog"
import { createEffect, createMemo, createResource, createSignal, For, onCleanup, onMount, Show } from "solid-js"
import { useGlobal } from "@/context/global"
import { useLanguage } from "@/context/language"
import { ServerConnection } from "@/context/server"
import {
  absoluteTreePath,
  activeTreeNavigation,
  advanceTreePreload,
  nextSuggestionIndex,
  nextTreeScrollTop,
  pickerFileSearchQuery,
  pickerAbsoluteInput,
  pickerMode,
  preloadTreeDirectories,
  cleanPickerInput,
  createPriorityTaskQueue,
  createDirectorySearch,
  currentPickerSuggestions,
  displayPickerPath,
  pickerParent,
  pickerRoot,
} from "./directory-picker-domain"
import "./dialog-select-directory-v2.css"
import { DividerV2 } from "@opencode-ai/ui/v2/divider-v2"
import { createStore } from "solid-js/store"
import { pickerRelativePath } from "./directory-picker-domain"

interface DialogSelectDirectoryV2Props {
  title?: string
  multiple?: boolean
  onSelect: (result: string | string[] | null) => void
  server: ServerConnection.Any
  mode?: "directory" | "file"
  start?: string
  authorizedRoots?: ReadonlyArray<{ directory: string; access: "read" | "write" }>
  validateSelection?: (directory: string) => Promise<string>
}

export function DialogSelectDirectoryV2(props: DialogSelectDirectoryV2Props) {
  const global = useGlobal()
  const { sync, sdk } = global.ensureServerCtx(props.server)
  const dialog = useDialog()
  const language = useLanguage()
  const policy = pickerMode(props.mode ?? "directory", props.start)
  const action = {
    file: language.t("dialog.directory.action.selectFile"),
    directory: language.t("dialog.directory.action.selectFolder"),
  }
  const [root, setRoot] = createSignal("")
  const [input, setInput] = createSignal("")
  const [selected, setSelected] = createSignal("")
  const [suggestionsOpen, setSuggestionsOpen] = createSignal(false)
  const [activeSuggestion, setActiveSuggestion] = createSignal(-1)
  const [loading, setLoading] = createSignal(false)
  const [error, setError] = createSignal(false)
  const [rootValid, setRootValid] = createSignal(false)
  const [validation, setValidation] = createStore({ pending: false, error: "" })
  const permitted = (directory: string) => !props.authorizedRoots || props.authorizedRoots.some(item =>
    pickerRelativePath(item.directory, directory) !== undefined)
  const activeRoot = createMemo(() => props.authorizedRoots?.filter(item => pickerRelativePath(item.directory, root()) !== undefined)
    .sort((left, right) => right.directory.length - left.directory.length)[0]?.directory)
  const listings = new Map<string, Promise<Array<{ name: string; type: "file" | "directory" }> | undefined>>()
  const loads = createPriorityTaskQueue<Array<{ name: string; type: "file" | "directory" }> | undefined>(3)
  const advanced = new Set<string>()
  let tree: FileTree | undefined
  let container: HTMLDivElement | undefined
  let pathArea: HTMLDivElement | undefined
  let navigation = 0

  const missingBase = createMemo(() => !props.authorizedRoots && !props.start && !(sync.data.path.home || sync.data.path.directory))
  const [fallbackPath] = createResource(
    () => (missingBase() ? true : undefined),
    () =>
      sdk.client.path
        .get()
        .then((result) => result.data)
        .catch(() => undefined),
    { initialValue: undefined },
  )
  const home = createMemo(() => props.authorizedRoots ? activeRoot() ?? props.start ?? "" : sync.data.path.home || fallbackPath()?.home || "")
  const start = createMemo(
    () =>
      props.authorizedRoots ? props.start : props.start ||
      sync.data.path.home ||
      sync.data.path.directory ||
      fallbackPath()?.home ||
      fallbackPath()?.directory,
  )
  const search = createDirectorySearch({ sdk, home, base: () => root() || start(), roots: () => props.authorizedRoots?.map(item => item.directory) })
  const [suggestions] = createResource(input, async (value) => {
    const typed = cleanPickerInput(value).replace(/\/+$/, "")
    const current = displayPickerPath(root(), value, home()).replace(/\/+$/, "")
    if (!typed || typed === current) return { query: value, items: [] }
    const directories = (await search(value)).map((absolute) => ({ absolute, type: "directory" as const }))
    if (!policy.includeFiles) return { query: value, items: directories.slice(0, 5) }
    const files = await sdk.client.find
      .files({ directory: root(), query: pickerFileSearchQuery(root(), value, home()), type: "file", limit: 20 })
      .then((result) => result.data ?? [])
      .catch(() => [])
    const results = [
      ...directories,
      ...files.map((path) => ({ absolute: absoluteTreePath(root(), path), type: "file" as const })),
    ]
    return {
      query: value,
      items: Array.from(new Map(results.map((result) => [result.absolute, result])).values()).slice(0, 8),
    }
  })
  const currentSuggestions = createMemo(() => currentPickerSuggestions(suggestions(), input()))

  async function load(path: string, generation: number, eager = false) {
    const key = path.replace(/\/+$/, "")
    setError(false)
    const absolute = absoluteTreePath(root(), key)
    if (!permitted(absolute)) return false
    const existing = listings.get(key)
    if (existing && !eager) loads.promote(`${generation}:${key}`)
    const request =
      existing ??
      loads.schedule(`${generation}:${key}`, eager ? "background" : "user", () => {
        if (!activeTreeNavigation(generation, navigation)) return Promise.resolve(undefined)
        return sdk.client.file
          .list({ directory: absolute, path: "" })
          .then((result) => result.error ? undefined : result.data)
          .catch(() => undefined)
      })
    listings.set(key, request)
    const nodes = await request
    if (!activeTreeNavigation(generation, navigation)) return false
    if (!nodes) {
      listings.delete(key)
      if (!key) setError(true)
      return false
    }
    tree?.batch(policy.entries(key, nodes).map((item) => ({ type: "add", path: item })))
    if (!eager && advanceTreePreload(advanced, key)) {
      for (const directory of preloadTreeDirectories(key, nodes)) void load(directory, generation, true)
    }
    return true
  }

  async function navigate(path: string) {
    const value = policy.navigation(pickerAbsoluteInput(cleanPickerInput(path), home(), root() || start() || home()))
    if (!value || !permitted(value)) {
      setValidation("error", "请选择当前身份在研究宿主上的授权工作目录。")
      return
    }
    setValidation("error", "")
    const token = ++navigation
    setLoading(true)
    setRootValid(false)
    setSelected("")
    setSuggestionsOpen(false)
    setActiveSuggestion(-1)
    setRoot(value)
    setInput(displayPickerPath(value, value, home()))
    listings.clear()
    advanced.clear()
    tree?.resetPaths([])
    const valid = await load("", token)
    if (!activeTreeNavigation(token, navigation)) return
    setRootValid(valid)
    setLoading(false)
  }

  function complete() {
    const items = currentSuggestions()
    const match = items[activeSuggestion()] ?? items[0]
    if (!match) return
    const value = displayPickerPath(match.absolute, input(), home())
    setInput(match.type === "directory" && !value.endsWith("/") ? value + "/" : value)
    if (match.type === "file") {
      setSelected(policy.selection(root(), pickerFileSearchQuery(root(), match.absolute, home())) ?? "")
      setSuggestionsOpen(false)
      setActiveSuggestion(-1)
    }
  }

  function chooseSuggestion(suggestion: { absolute: string; type: "file" | "directory" }) {
    if (suggestion.type === "directory") {
      void navigate(suggestion.absolute)
      return
    }
    setInput(displayPickerPath(suggestion.absolute, input(), home()))
    setSelected(policy.selection(root(), pickerFileSearchQuery(root(), suggestion.absolute, home())) ?? "")
    setSuggestionsOpen(false)
    setActiveSuggestion(-1)
  }

  function moveSuggestion(delta: -1 | 1) {
    setSuggestionsOpen(true)
    setActiveSuggestion((current) => nextSuggestionIndex(current, delta, currentSuggestions().length))
  }

  function activeSuggestionValue() {
    const items = currentSuggestions()
    return items[activeSuggestion()] ?? items[0]
  }

  const keyActions: Partial<Record<string, () => void>> = {
    ArrowDown: () => moveSuggestion(1),
    ArrowUp: () => moveSuggestion(-1),
    Enter: () => {
      const suggestion = activeSuggestionValue()
      if (suggestion) chooseSuggestion(suggestion)
      if (!suggestion) void navigate(input())
    },
    Tab: complete,
  }

  function handleInputKey(event: KeyboardEvent) {
    const action = keyActions[event.key]
    if (!action) return
    if (event.key === "Tab" && event.shiftKey) return
    event.preventDefault()
    action()
  }

  async function resolve() {
    const path = policy.result(root(), selected(), rootValid())
    if (!path || validation.pending || !permitted(path)) return
    const token = navigation
    setValidation({ pending: true, error: "" })
    try {
      const validated = props.validateSelection ? await props.validateSelection(path) : path
      if (!activeTreeNavigation(token, navigation) || policy.result(root(), selected(), rootValid()) !== path) return
      props.onSelect(props.multiple ? [validated] : validated)
      dialog.close()
    } catch (error) {
      if (activeTreeNavigation(token, navigation)) setValidation("error", error instanceof Error ? error.message : "工作区授权核对失败，请重试。")
    } finally { setValidation("pending", false) }
  }

  function cancel() {
    // Return cancellation explicitly so callers do not depend on the dialog
    // provider's close callback ordering.
    props.onSelect(null)
    dialog.close()
  }

  onMount(() => {
    const closeSuggestions = (event: PointerEvent) => {
      if (pathArea?.contains(event.target as Node)) return
      setSuggestionsOpen(false)
      setActiveSuggestion(-1)
    }
    document.addEventListener("pointerdown", closeSuggestions)
    onCleanup(() => document.removeEventListener("pointerdown", closeSuggestions))
    tree = new FileTree({
      paths: [],
      flattenEmptyDirectories: false,
      initialExpansion: "closed",
      stickyFolders: true,
      unsafeCSS: `
        button[data-type="item"] {
          background: transparent !important;
          box-shadow: none !important;
        }
        button[data-type="item"]:hover {
          background: var(--v2-overlay-simple-overlay-hover) !important;
        }
        button[data-type="item"]:focus-visible {
          outline: none !important;
          box-shadow: none !important;
        }
        [data-file-tree-virtualized-scroll] {
          overscroll-behavior: contain;
          scrollbar-width: thin;
        }
      `,
      onExpansionChange(change) {
        if (change.expanded) void load(change.path, navigation)
      },
      onSelectionChange(paths) {
        if (validation.pending) return
        const path = paths.at(-1)
        setSelected(path ? (policy.selection(root(), path) ?? "") : "")
      },
    })
    if (!container) return
    tree.render({ containerWrapper: container })
    tree.getFileTreeContainer()?.classList.add("directory-picker-v2-tree")
  })

  createEffect(() => {
    const path = start()
    if (!path || root()) return
    void navigate(path)
  })

  onCleanup(() => { navigation += 1; tree?.cleanUp() })

  return (
    <Dialog size="large" class="directory-picker-v2">
      <DialogHeader>
        <DialogTitle>{props.title ?? language.t("command.project.open")}</DialogTitle>
      </DialogHeader>
      <DividerV2 />
      <DialogBody class="directory-picker-v2-body pt-4!">
        <Show when={props.authorizedRoots && props.authorizedRoots.length > 1}>
          <div class="flex max-h-36 flex-col gap-2 mb-3 overflow-y-auto">
            <span class="text-12 text-v2-text-text-muted">选择研究宿主上的工作区</span>
            <For each={props.authorizedRoots}>{item => <ButtonV2 size="normal" variant={activeRoot() === item.directory ? "contrast" : "neutral"}
              class="justify-start! min-w-0" disabled={validation.pending} onClick={() => void navigate(item.directory)}>
              <span class="truncate" title={item.directory}>{item.directory}</span>
              <Show when={item.access === "read"}><span class="shrink-0">只读</span></Show>
            </ButtonV2>}</For>
          </div>
        </Show>
        <div class="directory-picker-v2-path" ref={pathArea}>
          <TextInputV2
            value={input()}
            autofocus
            autocomplete="off"
            spellcheck={false}
            disabled={validation.pending || !!props.authorizedRoots && !root()}
            class="!w-full"
            onInput={(event) => {
              setInput(cleanPickerInput(event.currentTarget.value))
              setSelected("")
              setSuggestionsOpen(true)
              setActiveSuggestion(-1)
            }}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={suggestionsOpen()}
            aria-controls="directory-picker-v2-suggestions"
            aria-activedescendant={
              activeSuggestion() >= 0 ? `directory-picker-v2-suggestion-${activeSuggestion()}` : undefined
            }
            onKeyDown={handleInputKey}
          />
          <div class="directory-picker-v2-actions">
            <ButtonV2 size="small" variant="ghost" disabled={validation.pending || !home()} onClick={() => void navigate(home())}>
              ~
            </ButtonV2>
            <ButtonV2 size="small" variant="ghost" disabled={validation.pending || !root()} onClick={() => void navigate(activeRoot() || pickerRoot(root()) || root())}>
              {language.t("dialog.directory.root")}
            </ButtonV2>
            <ButtonV2 size="small" variant="ghost" disabled={validation.pending || !root() || !permitted(pickerParent(root()))} onClick={() => void navigate(pickerParent(root()))}>
              {language.t("dialog.directory.parent")}
            </ButtonV2>
          </div>
          <Show when={suggestionsOpen() && currentSuggestions().length > 0}>
            <div id="directory-picker-v2-suggestions" role="listbox" class="directory-picker-v2-suggestions">
              <For each={currentSuggestions()}>
                {(suggestion, index) => (
                  <button
                    id={`directory-picker-v2-suggestion-${index()}`}
                    role="option"
                    aria-selected={index() === activeSuggestion()}
                    data-active={index() === activeSuggestion() ? "" : undefined}
                    onPointerMove={() => setActiveSuggestion(index())}
                    onClick={() => chooseSuggestion(suggestion)}
                  >
                    {displayPickerPath(suggestion.absolute, input(), home())}
                    {suggestion.type === "directory" ? "/" : ""}
                  </button>
                )}
              </For>
            </div>
          </Show>
        </div>
        <div
          class="directory-picker-v2-browser"
          ref={container}
          onWheel={(event) => {
            const scroller = tree
              ?.getFileTreeContainer()
              ?.shadowRoot?.querySelector<HTMLElement>("[data-file-tree-virtualized-scroll]")
            if (!scroller) return
            const next = nextTreeScrollTop(
              scroller.scrollTop,
              event.deltaY,
              scroller.scrollHeight,
              scroller.clientHeight,
            )
            if (next === scroller.scrollTop) return
            event.preventDefault()
            scroller.scrollTop = next
            scroller.dispatchEvent(new Event("scroll"))
          }}
        >
          <Show when={loading()}>
            <div class="directory-picker-v2-state">{language.t("common.loading")}</div>
          </Show>
          <Show when={!loading() && error()}>
            <div class="directory-picker-v2-state">{language.t("dialog.directory.readError")}</div>
          </Show>
          <Show when={props.authorizedRoots && !root()}><div class="directory-picker-v2-state">请先选择一个授权工作区</div></Show>
        </div>
        <div class="directory-picker-v2-selection">{policy.result(root(), selected(), rootValid())}</div>
        <Show when={validation.error}><div role="alert" class="text-12 text-text-critical-base">{validation.error}</div></Show>
      </DialogBody>
      <DialogFooter>
        <ButtonV2 variant="neutral" onClick={cancel}>
          {language.t("common.cancel")}
        </ButtonV2>
        <ButtonV2 variant="contrast" disabled={validation.pending || !policy.result(root(), selected(), rootValid())} onClick={() => void resolve()}>
          {validation.pending ? "正在核对工作区…" : action[policy.action]}
        </ButtonV2>
      </DialogFooter>
    </Dialog>
  )
}
