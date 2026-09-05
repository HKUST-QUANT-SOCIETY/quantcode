import { describe, expect, test } from "bun:test"
import { dict as en } from "./en"
import { dict as ar } from "./ar"
import { dict as br } from "./br"
import { dict as bs } from "./bs"
import { dict as da } from "./da"
import { dict as de } from "./de"
import { dict as es } from "./es"
import { dict as fr } from "./fr"
import { dict as ja } from "./ja"
import { dict as ko } from "./ko"
import { dict as no } from "./no"
import { dict as pl } from "./pl"
import { dict as ru } from "./ru"
import { dict as uk } from "./uk"
import { dict as th } from "./th"
import { dict as zh } from "./zh"
import { dict as zht } from "./zht"
import { dict as tr } from "./tr"

const locales = [ar, br, bs, da, de, es, fr, ja, ko, no, pl, ru, uk, th, tr, zh, zht]

const prefixes = ["provider.", "dialog.provider.", "settings.providers."]
const providerKeys = (Object.keys(en) as string[]).filter((key) =>
  prefixes.some((prefix) => key.startsWith(prefix)),
)
const sessionKeys = ["command.session.previous.unseen", "command.session.next.unseen"] as const

describe("i18n parity", () => {
  test("non-English locales define all provider/dialog-provider/settings-providers keys", () => {
    expect(providerKeys.length).toBeGreaterThan(0)
    for (const locale of locales) {
      const dict = locale as Record<string, string | undefined>
      for (const key of providerKeys) {
        expect(dict[key]).toBeDefined()
      }
    }
  })
  test("non-English locales translate targeted unseen session keys", () => {
    for (const locale of locales) {
      const dict = locale as Record<string, string | undefined>
      for (const key of sessionKeys) {
        expect(dict[key]).toBeDefined()
        expect(dict[key]).not.toBe(en[key])
      }
    }
  })
})
