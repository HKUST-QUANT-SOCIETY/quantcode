import { isQuantCode } from "@/brand"
import { Button } from "@opencode-ai/ui/button"
import { useDialog } from "@opencode-ai/ui/context/dialog"
import { Dialog } from "@opencode-ai/ui/dialog"
import { IconButton } from "@opencode-ai/ui/icon-button"
import { useMutation } from "@tanstack/solid-query"
import { TextField } from "@opencode-ai/ui/text-field"
import { showToast } from "@/utils/toast"
import { batch, createEffect, createSignal, onCleanup, For, Show } from "solid-js"
import { createStore, produce } from "solid-js/store"
import { Link } from "@/components/link"
import { useServerSDK } from "@/context/server-sdk"
import { useServerSync } from "@/context/server-sync"
import { useLanguage } from "@/context/language"
import { type FormState, headerRow, modelRow, modelConnectionURL, validateCustomProvider } from "./dialog-custom-provider-form"

const segmenter =
  typeof Intl !== "undefined" && "Segmenter" in Intl
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : undefined

function first(value: string) {
  if (!value) return ""
  if (!segmenter) return Array.from(value)[0] ?? ""
  return segmenter.segment(value)[Symbol.iterator]().next().value?.segment ?? Array.from(value)[0] ?? ""
}

const slugify = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-_]+/g, "-")
    .replace(/^[-_]+/, "")
    .replace(/[-_]+$/, "")

const ENV_KEY = /^\{env:[^}]+\}$/

export function DialogCustomProvider(props: { product?: "quantcode" | "opencode"; providerID?: string } = {}) {
  const dialog = useDialog()
  const serverSync = useServerSync()
  const serverSDK = useServerSDK()
  const language = useLanguage()

  const host = serverSDK()
  const sync = serverSync()
  const connection = JSON.stringify(host.server)
  const lifetime = new AbortController()
  const [connectionState, setConnectionState] = createStore({ stale: false })
  let modelRequest: AbortController | undefined
  let formVersion = 0
  const current = () => !lifetime.signal.aborted && serverSDK() === host && JSON.stringify(host.server) === connection
  createEffect(() => {
    if (serverSDK() !== host || JSON.stringify(host.server) !== connection) {
      lifetime.abort()
      modelRequest?.abort()
      setConnectionState("stale", true)
    }
  })
  onCleanup(() => { lifetime.abort(); modelRequest?.abort() })
  const requireCurrent = () => { if (!current()) throw new Error("研究宿主已变化，请在所选宿主重新打开模型设置。") }
  const changed = () => { formVersion++; modelRequest?.abort() }

  const quantcode = () => props.product ? props.product === "quantcode" : isQuantCode
  const existing = props.providerID ? sync.data.config.provider?.[props.providerID] : undefined
  const [form, setForm] = createStore<FormState>({
    providerID: props.providerID ?? "",
    name: existing?.name ?? "",
    baseURL: existing?.options?.baseURL ?? "",
    apiKey: "",
    models: existing?.models ? Object.entries(existing.models).map(([id, model]) => ({ ...modelRow(), id, name: model.name ?? id })) : [modelRow()],
    headers: existing?.options?.headers ? Object.entries(existing.options.headers).map(([key, value]) => ({ ...headerRow(), key, value })) : [headerRow()],
    err: {},
  })
  const [providerIDEdited, setProviderIDEdited] = createSignal(!!props.providerID)
  const [fetching, setFetching] = createSignal(false)

  const goBack = () => {
    dialog.close()
  }

  const addModel = () => {
    changed()
    setForm(
      "models",
      produce((rows) => {
        rows.push(modelRow())
      }),
    )
  }

  const removeModel = (index: number) => {
    if (form.models.length <= 1) return
    changed()
    setForm(
      "models",
      produce((rows) => {
        rows.splice(index, 1)
      }),
    )
  }

  const addHeader = () => {
    setForm(
      "headers",
      produce((rows) => {
        rows.push(headerRow())
      }),
    )
  }

  const removeHeader = (index: number) => {
    if (form.headers.length <= 1) return
    setForm(
      "headers",
      produce((rows) => {
        rows.splice(index, 1)
      }),
    )
  }

  const setField = (key: "providerID" | "name" | "baseURL" | "apiKey", value: string) => {
    changed()
    batch(() => {
      if (key === "baseURL" && quantcode() && !props.providerID) {
        try {
          const host = new URL(value.trim()).hostname
          setForm("name", host)
          setForm("providerID", "qc-" + slugify(host))
        } catch { /* A partial URL is validated on submit. */ }
      }
      if (key === "providerID") setProviderIDEdited(true)
      if (key === "name" && !providerIDEdited()) {
        setForm("providerID", slugify(value))
        setForm("err", "providerID", undefined)
      }
      setForm(key, value)
      if (key !== "apiKey") setForm("err", key, undefined)
    })
  }

  const setModel = (index: number, key: "id" | "name", value: string) => {
    changed()
    batch(() => {
      setForm("models", index, key, value)
      setForm("models", index, "err", key, undefined)
    })
  }

  const setHeader = (index: number, key: "key" | "value", value: string) => {
    batch(() => {
      setForm("headers", index, key, value)
      setForm("headers", index, "err", key, undefined)
    })
  }

  const validate = () => {
    if (quantcode() && ((!props.providerID && !form.apiKey.trim()) || ENV_KEY.test(form.apiKey.trim()))) {
      showToast({ title: "请输入 API Key", description: "QuantCode 使用 URL 与 API Key 连接模型接口。" })
      return
    }
    if (quantcode() && props.providerID && !form.apiKey.trim() &&
        modelConnectionURL(form.baseURL.trim()) !== modelConnectionURL(existing?.options?.baseURL ?? "")) {
      showToast({ title: "请重新输入 API Key", description: "接口地址已变化，需要为新地址填写对应的密钥。" })
      return
    }
    const output = validateCustomProvider({
      form,
      t: language.t,
      disabledProviders: sync.data.config.disabled_providers ?? [],
      existingProviderIDs: new Set([...sync.data.provider.all.keys()].filter(id => id !== props.providerID)),
    })
    batch(() => {
      setForm("err", output.err)
      output.models.forEach((err, index) => setForm("models", index, "err", err))
      output.headers.forEach((err, index) => setForm("headers", index, "err", err))
    })
    return output.result
  }

  const saveMutation = useMutation(() => ({
    mutationFn: async (result: NonNullable<ReturnType<typeof validate>>) => {
      requireCurrent()
      const disabledProviders = sync.data.config.disabled_providers ?? []
      const nextDisabled = disabledProviders.filter((id) => id !== result.providerID)

      if (result.key) {
        const response = await host.client.auth.set({
          providerID: result.providerID,
          auth: {
            type: "api",
            key: result.key,
            ...(quantcode() ? { metadata: { quantcode_base_url: modelConnectionURL(result.config.options.baseURL)! } } : {}),
          },
        }, { signal: lifetime.signal, redirect: "error" })
        if (response.error) throw new Error("凭据保存失败，请重试。")
      }

      requireCurrent()
      await sync.updateConfig({
        provider: { [result.providerID]: { ...existing, ...result.config, options: { ...existing?.options, ...result.config.options } } },
        disabled_providers: nextDisabled,
      })
      return result
    },
    onSuccess: (result) => {
      if (!current()) return
      dialog.close()
      showToast({
        variant: "success",
        icon: "circle-check",
        title: quantcode() ? "模型接口已保存" : language.t("provider.connect.toast.connected.title", { provider: result.name }),
        description: quantcode() ? "可在任务中选择模型。" : language.t("provider.connect.toast.connected.description", { provider: result.name }),
      })
    },
    onError: (err) => {
      if (!current()) return
      const message = err instanceof Error ? err.message : String(err)
      showToast({ title: language.t("common.requestFailed"), description: message })
    },
  }))

  const save = (e: SubmitEvent) => {
    e.preventDefault()
    if (saveMutation.isPending) return

    const result = validate()
    if (!result) return
    saveMutation.mutate(result)
  }

  const isEnvKey = () => ENV_KEY.test(form.apiKey.trim())
  const canFetchModels = () => !!modelConnectionURL(form.baseURL.trim()) && !isEnvKey() && current()

  const parseModelIDs = (json: unknown) => {
    const list = Array.isArray((json as { data?: unknown })?.data)
      ? ((json as { data: unknown[] }).data as unknown[])
      : Array.isArray(json)
        ? json
        : []
    return Array.from(
      new Set(
        list
          .map((item) => (typeof item === "string" ? item : (item as { id?: unknown })?.id))
          .filter((id): id is string => typeof id === "string" && id.trim().length > 0)
          .map((id) => id.trim()),
      ),
    )
  }

  // Second hop: ask the local OpenCode server to probe the URL without any
  // credentials. Used when the browser cannot reach the provider directly
  // (CORS, mixed content, TLS).
  const fetchModelsViaServer = async (baseURL: string, signal: AbortSignal) => {
    const response = await host.client.experimental.proxy.models({ url: baseURL }, { signal })
    if (response.error || !response.data) throw new Error(language.t("provider.custom.error.fetchFailed"))
    const json = response.data
    if (!json.reachable) throw new Error(language.t("provider.custom.error.fetchFailed"))
    if (!json.models || json.models.length === 0) throw new Error(language.t("provider.custom.error.fetchFailed"))
    return json.models
  }

  const applyModels = (ids: string[]) => {
    setForm(
      "models",
      ids.map((id) => ({ ...modelRow(), id, name: id })),
    )
  }

  const fetchModels = async () => {
    if (fetching() || !canFetchModels()) return
    setFetching(true)
    const version = formVersion
    const controller = new AbortController()
    modelRequest = controller
    const signal = AbortSignal.any([controller.signal, lifetime.signal])
    const valid = () => current() && !signal.aborted && formVersion === version
    try {
      const baseURL = form.baseURL.trim()
      const apiKey = form.apiKey.trim()
      try {
        const response = await fetch(new URL("models", baseURL.endsWith("/") ? baseURL : `${baseURL}/`), {
          ...(apiKey ? { headers: { Authorization: `Bearer ${apiKey}` } } : {}),
          redirect: "error", credentials: "omit",
          signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]),
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const ids = parseModelIDs(await response.json())
        if (ids.length === 0) throw new Error(language.t("provider.custom.error.fetchFailed"))
        if (valid()) applyModels(ids)
      } catch {
        // Direct browser fetch failed (network, CORS, mixed content): retry
        // through the server's credential-free probe endpoint before giving up.
        if (!valid()) return
        const ids = await fetchModelsViaServer(baseURL, AbortSignal.any([signal, AbortSignal.timeout(15_000)]))
        if (valid()) applyModels(ids)
      }
    } catch (err) {
      if (!valid()) return
      const message = err instanceof Error ? err.message : String(err)
      showToast({ title: language.t("provider.custom.error.fetchFailed"), description: message })
    } finally {
      if (modelRequest === controller) { modelRequest = undefined; setFetching(false) }
    }
  }

  const initial = () => first(form.name.trim() || form.providerID.trim() || "?")

  return (
    <Dialog
      title={quantcode() ? "QuantCode 模型供应商" :
        <IconButton
          tabIndex={-1}
          icon="arrow-left"
          variant="ghost"
          onClick={goBack}
          aria-label={language.t("common.goBack")}
        />
      }
      transition
    >
      <div class="flex min-h-0 flex-col gap-6 px-2.5 max-h-[70vh]">
        <Show when={connectionState.stale}><p role="alert" class="px-2.5 text-14-regular text-text-base">研究宿主已变化。请关闭此窗口，在所选宿主重新打开模型设置。</p></Show>
        <Show when={!quantcode()}><div class="px-2.5 flex shrink-0 gap-4 items-center">
          <div class="size-5 shrink-0 rounded-full bg-surface-raised-base flex items-center justify-center text-11-medium text-text-base uppercase">
            {initial()}
          </div>
          <div class="text-16-medium text-text-strong">{quantcode() ? "QuantCode 模型供应商" : language.t("provider.custom.title")}</div>
        </div></Show>

        <form onSubmit={save} class="flex min-h-0 flex-col">
          <div class="px-2.5 pb-4 flex min-h-0 flex-col gap-6 overflow-y-auto">
          <Show when={quantcode()} fallback={<p class="text-14-regular text-text-base">
            {language.t("provider.custom.description.prefix")}
            <Link href="https://opencode.ai/docs/providers/#custom-provider" tabIndex={-1}>
              {language.t("provider.custom.description.link")}
            </Link>
            {language.t("provider.custom.description.suffix")}
          </p>}>
            <p class="text-14-regular text-text-base">输入 OpenAI 兼容接口的 URL 和 API Key，凭据保存在当前研究宿主。保存后可在 QuantCode 任务中选择该接口提供的模型。</p>
          </Show>

          <div class="flex flex-col gap-4">
            <Show when={!quantcode()}>
            <TextField
              autofocus
              label={language.t("provider.custom.field.name.label")}
              placeholder={language.t("provider.custom.field.name.placeholder")}
              value={form.name}
              onChange={(v) => setField("name", v)}
              validationState={form.err.name ? "invalid" : undefined}
              error={form.err.name}
            />
            <TextField
              disabled={!!props.providerID}
              label={language.t("provider.custom.field.providerID.label")}
              placeholder={language.t("provider.custom.field.providerID.placeholder")}
              description={language.t("provider.custom.field.providerID.auto")}
              value={form.providerID}
              onChange={(v) => setField("providerID", v)}
              validationState={form.err.providerID ? "invalid" : undefined}
              error={form.err.providerID}
            />
            </Show>
            <TextField
              autofocus={quantcode()}
              label={quantcode() ? "接口 URL" : language.t("provider.custom.field.baseURL.label")}
              placeholder={language.t("provider.custom.field.baseURL.placeholder")}
              value={form.baseURL}
              onChange={(v) => setField("baseURL", v)}
              validationState={form.err.baseURL ? "invalid" : undefined}
              error={form.err.baseURL}
            />
            <TextField
              type="password"
              autocomplete="new-password"
              label={language.t("provider.custom.field.apiKey.label")}
              placeholder={language.t("provider.custom.field.apiKey.placeholder")}
              description={props.providerID ? "地址不变时可留空保留凭据；更改地址须重新填写对应密钥。" : quantcode() ? "输入该接口的 API Key，不会回显已保存的密钥。" : language.t("provider.custom.field.apiKey.description")}
              value={form.apiKey}
              onChange={(v) => setField("apiKey", v)}
            />
          </div>

          <div class="flex flex-col gap-3">
            <div class="flex items-center justify-between gap-2">
              <label class="text-12-medium text-text-weak">{language.t("provider.custom.models.label")}</label>
              <Show
                when={isEnvKey()}
                fallback={
                  <Button
                    type="button"
                    size="small"
                    variant="ghost"
                    icon="arrow-down-to-line"
                    onClick={() => void fetchModels()}
                    disabled={fetching() || !canFetchModels()}
                  >
                    {fetching()
                      ? language.t("provider.custom.status.fetching")
                      : language.t("provider.custom.action.fetchModels")}
                  </Button>
                }
              >
                <span class="text-12-regular text-text-weak">{quantcode() ? "请输入接口的实际 API Key。" : language.t("provider.custom.hint.apiKeyEnv")}</span>
              </Show>
            </div>
            <For each={form.models}>
              {(m, i) => (
                <div class="flex gap-2 items-start" data-row={m.row}>
                  <div class="flex-1">
                    <TextField
                      label={language.t("provider.custom.models.id.label")}
                      hideLabel
                      placeholder={language.t("provider.custom.models.id.placeholder")}
                      value={m.id}
                      onChange={(v) => setModel(i(), "id", v)}
                      validationState={m.err.id ? "invalid" : undefined}
                      error={m.err.id}
                    />
                  </div>
                  <div class="flex-1">
                    <TextField
                      label={language.t("provider.custom.models.name.label")}
                      hideLabel
                      placeholder={language.t("provider.custom.models.name.placeholder")}
                      value={m.name}
                      onChange={(v) => setModel(i(), "name", v)}
                      validationState={m.err.name ? "invalid" : undefined}
                      error={m.err.name}
                    />
                  </div>
                  <IconButton
                    type="button"
                    icon="trash"
                    variant="ghost"
                    class="mt-1.5"
                    onClick={() => removeModel(i())}
                    disabled={form.models.length <= 1}
                    aria-label={language.t("provider.custom.models.remove")}
                  />
                </div>
              )}
            </For>
            <Button type="button" size="small" variant="ghost" icon="plus-small" onClick={addModel} class="self-start">
              {language.t("provider.custom.models.add")}
            </Button>
          </div>

          <Show when={!quantcode()}><div class="flex flex-col gap-3">
            <label class="text-12-medium text-text-weak">{language.t("provider.custom.headers.label")}</label>
            <For each={form.headers}>
              {(h, i) => (
                <div class="flex gap-2 items-start" data-row={h.row}>
                  <div class="flex-1">
                    <TextField
                      label={language.t("provider.custom.headers.key.label")}
                      hideLabel
                      placeholder={language.t("provider.custom.headers.key.placeholder")}
                      value={h.key}
                      onChange={(v) => setHeader(i(), "key", v)}
                      validationState={h.err.key ? "invalid" : undefined}
                      error={h.err.key}
                    />
                  </div>
                  <div class="flex-1">
                    <TextField
                      label={language.t("provider.custom.headers.value.label")}
                      hideLabel
                      placeholder={language.t("provider.custom.headers.value.placeholder")}
                      value={h.value}
                      onChange={(v) => setHeader(i(), "value", v)}
                      validationState={h.err.value ? "invalid" : undefined}
                      error={h.err.value}
                    />
                  </div>
                  <IconButton
                    type="button"
                    icon="trash"
                    variant="ghost"
                    class="mt-1.5"
                    onClick={() => removeHeader(i())}
                    disabled={form.headers.length <= 1}
                    aria-label={language.t("provider.custom.headers.remove")}
                  />
                </div>
              )}
            </For>
            <Button type="button" size="small" variant="ghost" icon="plus-small" onClick={addHeader} class="self-start">
              {language.t("provider.custom.headers.add")}
            </Button>
          </div>

          </Show>
          </div>
          <div class="px-2.5 py-4 shrink-0 border-t border-border-weak-base">
          <Button
            class="w-auto self-start"
            type="submit"
            size="large"
            variant="primary"
            disabled={saveMutation.isPending || connectionState.stale}
          >
            {saveMutation.isPending ? language.t("common.saving") : quantcode() ? "保存 QuantCode 供应商" : language.t("common.submit")}
          </Button>
          </div>
        </form>
      </div>
    </Dialog>
  )
}
