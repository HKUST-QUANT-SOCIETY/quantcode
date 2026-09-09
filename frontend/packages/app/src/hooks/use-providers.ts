import { isQuantCode } from "@/brand"
import { useServerSync } from "@/context/server-sync"
import { decode64 } from "@/utils/base64"
import { useParams } from "@solidjs/router"
import { Iterable, pipe } from "effect"
import type { Accessor } from "solid-js"
import { selectProviderCatalog } from "./provider-catalog"

export function useProviders(directory?: Accessor<string | undefined>) {
  const serverSync = useServerSync()
  const params = useParams()
  const dir = () => (directory ? directory() : decode64(params.dir))
  const rawProviders = () => {
    const value = dir()
    const projectStore = value ? serverSync().child(value)[0] : undefined
    if (directory)
      return selectProviderCatalog({
        explicit: true,
        directory: value,
        catalog: projectStore && { ready: projectStore.provider_ready, providers: projectStore.provider },
      })
    return selectProviderCatalog({
      explicit: false,
      directory: value,
      catalog: projectStore && { ready: projectStore.provider_ready, providers: projectStore.provider },
      global: serverSync().data.provider,
    })
  }
  const providers = () => {
    const catalog = rawProviders()
    if (!isQuantCode) return catalog
    const ids = new Set(Object.entries(serverSync().data.config.provider ?? {})
      .filter(([, value]) => value.npm === "@ai-sdk/openai-compatible" && typeof value.options?.baseURL === "string" && /^https?:\/\//.test(value.options.baseURL))
      .map(([id]) => id))
    return { all: new Map([...catalog.all].filter(([id]) => ids.has(id))),
      connected: catalog.connected.filter(id => ids.has(id)),
      default: Object.fromEntries(Object.entries(catalog.default).filter(([id]) => ids.has(id))) }
  }
  const connected = () => {
    const connectedIDs = new Set(providers().connected)
    return pipe(
      providers().all,
      Iterable.map(([, p]) => p),
      Iterable.filter((p) => connectedIDs.has(p.id)),
      (v) => Array.from(v),
    )
  }
  return {
    all: () => providers().all,
    default: () => providers().default,
    connected,
    paid: connected,
  }
}
