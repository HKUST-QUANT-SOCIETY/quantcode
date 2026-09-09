import { Button } from "@opencode-ai/ui/button"
import { useDialog } from "@opencode-ai/ui/context/dialog"
import { Dialog } from "@opencode-ai/ui/dialog"
import { TextField } from "@opencode-ai/ui/text-field"
import { useMutation } from "@tanstack/solid-query"
import { Icon } from "@opencode-ai/ui/icon"
import { createEffect, createMemo, createResource, For, onCleanup, Show } from "solid-js"
import { createStore } from "solid-js/store"
import { type LocalProject, getAvatarColors } from "@/context/layout"
import { getFilename } from "@opencode-ai/core/util/path"
import { Avatar } from "@opencode-ai/ui/avatar"
import { useLanguage } from "@/context/language"
import { getProjectAvatarSource } from "@/pages/layout/helpers"
import { ServerConnection, useServer } from "@/context/server"
import { useGlobal } from "@/context/global"
import { isQuantCode } from "@/brand"
import { projectRuntime, saveProjectAppearance } from "./quantcode/project-actions"
import { errorMessage } from "@/pages/layout/helpers"

const AVATAR_COLOR_KEYS = ["pink", "mint", "orange", "purple", "cyan", "lime"] as const

export function DialogEditProject(props: { project: LocalProject; server: ServerConnection.Any }) {
  const dialog = useDialog()
  const global = useGlobal()
  const server = useServer()
  const language = useLanguage()
  // The form describes this project on this host, even if a different host
  // later exposes a project with the same ID. Capture before any interaction.
  const host = global.ensureServerCtx(props.server)
  const client = host.sdk.client
  const connection = JSON.stringify(props.server)
  const selectedServer = server.key
  const project = { id: props.project.id, directory: props.project.worktree }
  const [connectionState, setConnectionState] = createStore({ stale: false })
  let disposed = false
  const current = () => !disposed && !connectionState.stale && server.key === selectedServer &&
    JSON.stringify(props.server) === connection && global.ensureServerCtx(props.server).sdk.client === client &&
    props.project.id === project.id && props.project.worktree === project.directory
  createEffect(() => {
    if (!current()) setConnectionState("stale", true)
  })
  onCleanup(() => { disposed = true })
  const [runtime] = createResource(() => isQuantCode && current() ? client : undefined,
    async client => ({ client, mode: await projectRuntime(client) }))
  const mode = () => !current() ? undefined : !isQuantCode ? "legacy" : !runtime.loading && !runtime.error && runtime()?.client === client ? runtime()?.mode : undefined
  const requireCurrent = () => { if (!current()) throw new Error("研究宿主或项目已变化，请重新打开项目设置。") }

  const folderName = createMemo(() => getFilename(props.project.worktree))
  const defaultName = createMemo(() => props.project.name || folderName())

  const [store, setStore] = createStore({
    name: defaultName(),
    color: props.project.icon?.color,
    iconOverride: props.project.icon?.override,
    startup: props.project.commands?.start ?? "",
    dragOver: false,
    iconHover: false,
  })

  let iconInput: HTMLInputElement | undefined

  function handleFileSelect(file: File) {
    if (!file.type.startsWith("image/")) return
    const reader = new FileReader()
    reader.onload = (e) => {
      if (!current()) return
      setStore("iconOverride", e.target?.result as string)
      setStore("iconHover", false)
    }
    reader.readAsDataURL(file)
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault()
    setStore("dragOver", false)
    const file = e.dataTransfer?.files[0]
    if (file) handleFileSelect(file)
  }

  function handleDragOver(e: DragEvent) {
    e.preventDefault()
    setStore("dragOver", true)
  }

  function handleDragLeave() {
    setStore("dragOver", false)
  }

  function handleInputChange(e: Event) {
    const input = e.target as HTMLInputElement
    const file = input.files?.[0]
    if (file) handleFileSelect(file)
  }

  function clearIcon() {
    setStore("iconOverride", "")
  }

  const saveMutation = useMutation(() => ({
    mutationFn: async () => {
      requireCurrent()
      const currentMode = isQuantCode ? await projectRuntime(client) : "legacy"
      requireCurrent()
      const name = store.name.trim() === folderName() ? "" : store.name.trim()
      const start = store.startup.trim()

      if (project.id && project.id !== "global") {
        await saveProjectAppearance(client, {
          projectID: project.id,
          directory: project.directory,
          name,
          icon: { color: store.color || "", override: store.iconOverride || "" },
          start,
        }, currentMode)
        if (!current()) return
        host.sync.project.icon(project.directory, store.iconOverride || undefined)
        dialog.close()
        return
      }

      host.sync.project.meta(project.directory, {
        name,
        icon: { color: store.color || undefined, override: store.iconOverride || undefined },
        ...(currentMode === "legacy" ? { commands: { start: start || undefined } } : {}),
      })
      dialog.close()
    },
  }))

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault()
    if (saveMutation.isPending || !mode()) return
    saveMutation.mutate()
  }

  return (
    <Dialog title={language.t("dialog.project.edit.title")} class="w-full max-w-[480px] mx-auto">
      <form onSubmit={handleSubmit} class="flex flex-col gap-6 p-6 pt-0">
        <div class="flex flex-col gap-4">
          <TextField
            autofocus
            type="text"
            label={language.t("dialog.project.edit.name")}
            placeholder={folderName()}
            value={store.name}
            onChange={(v) => setStore("name", v)}
          />

          <div class="flex flex-col gap-2">
            <label class="text-12-medium text-text-weak">{language.t("dialog.project.edit.icon")}</label>
            <div class="flex gap-3 items-start">
              <div
                class="relative"
                onMouseEnter={() => setStore("iconHover", true)}
                onMouseLeave={() => setStore("iconHover", false)}
              >
                <div
                  class="relative size-16 rounded-md transition-colors cursor-pointer"
                  classList={{
                    "border-text-interactive-base bg-surface-info-base/20": store.dragOver,
                    "border-border-base hover:border-border-strong": !store.dragOver,
                    "overflow-hidden": !!store.iconOverride,
                  }}
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onClick={() => {
                    if (store.iconOverride && store.iconHover) {
                      clearIcon()
                    } else {
                      iconInput?.click()
                    }
                  }}
                >
                  <Show
                    when={getProjectAvatarSource(props.project.id, {
                      color: store.color,
                      url: props.project.icon?.url,
                      override: store.iconOverride,
                    })}
                    fallback={
                      <div class="size-full flex items-center justify-center">
                        <Avatar
                          fallback={store.name || defaultName()}
                          {...getAvatarColors(store.color)}
                          class="size-full text-[32px]"
                        />
                      </div>
                    }
                  >
                    {(src) => (
                      <img
                        src={src()}
                        alt={language.t("dialog.project.edit.icon.alt")}
                        class="size-full object-cover"
                      />
                    )}
                  </Show>
                </div>
                <div
                  class="absolute inset-0 size-16 bg-surface-raised-stronger-non-alpha/90 rounded-[6px] z-10 pointer-events-none flex items-center justify-center transition-opacity"
                  classList={{
                    "opacity-100": store.iconHover && !store.iconOverride,
                    "opacity-0": !(store.iconHover && !store.iconOverride),
                  }}
                >
                  <Icon name="cloud-upload" size="large" class="text-icon-on-interactive-base drop-shadow-sm" />
                </div>
                <div
                  class="absolute inset-0 size-16 bg-surface-raised-stronger-non-alpha/90 rounded-[6px] z-10 pointer-events-none flex items-center justify-center transition-opacity"
                  classList={{
                    "opacity-100": store.iconHover && !!store.iconOverride,
                    "opacity-0": !(store.iconHover && !!store.iconOverride),
                  }}
                >
                  <Icon name="trash" size="large" class="text-icon-on-interactive-base drop-shadow-sm" />
                </div>
              </div>
              <input
                id="icon-upload"
                ref={(el) => {
                  iconInput = el
                }}
                type="file"
                accept="image/*"
                class="hidden"
                onChange={handleInputChange}
              />
              <div class="flex flex-col gap-1.5 text-12-regular text-text-weak self-center">
                <span>{language.t("dialog.project.edit.icon.hint")}</span>
                <span>{language.t("dialog.project.edit.icon.recommended")}</span>
              </div>
            </div>
          </div>

          <Show when={!store.iconOverride}>
            <div class="flex flex-col gap-2">
              <label class="text-12-medium text-text-weak">{language.t("dialog.project.edit.color")}</label>
              <div class="flex gap-1.5">
                <For each={AVATAR_COLOR_KEYS}>
                  {(color) => (
                    <button
                      type="button"
                      aria-label={language.t("dialog.project.edit.color.select", { color })}
                      aria-pressed={store.color === color}
                      classList={{
                        "flex items-center justify-center size-10 p-0.5 rounded-lg overflow-hidden transition-colors cursor-default": true,
                        "bg-transparent border-2 border-icon-strong-base hover:bg-surface-base-hover":
                          store.color === color,
                        "bg-transparent border border-transparent hover:bg-surface-base-hover hover:border-border-weak-base":
                          store.color !== color,
                      }}
                      onClick={() => {
                        if (store.color === color && !props.project.icon?.url) return
                        setStore("color", store.color === color ? undefined : color)
                      }}
                    >
                      <Avatar
                        fallback={store.name || defaultName()}
                        {...getAvatarColors(color)}
                        class="size-full rounded"
                      />
                    </button>
                  )}
                </For>
              </div>
            </div>
          </Show>

          <Show when={mode() === "legacy"}><TextField
            multiline
            label={language.t("dialog.project.edit.worktree.startup")}
            description={language.t("dialog.project.edit.worktree.startup.description")}
            placeholder={language.t("dialog.project.edit.worktree.startup.placeholder")}
            value={store.startup}
            onChange={(v) => setStore("startup", v)}
            spellcheck={false}
            class="max-h-14 w-full overflow-y-auto font-mono text-xs"
          /></Show>
          <Show when={!mode()}><p role="status" class="text-12-regular text-text-weak">
            {connectionState.stale ? "研究宿主或项目已变化，请关闭后重新打开项目设置。" : runtime.loading ? "正在确认研究宿主…" : "无法确认研究宿主，请关闭后重试。"}
          </p></Show>
          <Show when={saveMutation.error}><p role="alert" class="text-12-regular text-text-critical-base">{errorMessage(saveMutation.error, "保存项目设置失败，请重试。")}</p></Show>
        </div>

        <div class="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="large" onClick={() => dialog.close()}>
            {language.t("common.cancel")}
          </Button>
          <Button type="submit" variant="primary" size="large" disabled={saveMutation.isPending || !mode()}>
            {saveMutation.isPending ? language.t("common.saving") : language.t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
