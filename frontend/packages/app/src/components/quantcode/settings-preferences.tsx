import { For, Show } from "solid-js"
import { useLanguage } from "@/context/language"
import { useSettings } from "@/context/settings"
import { usePlatform } from "@/context/platform"
import { SettingsKeybinds } from "../settings-keybinds"
import { useUpdaterAction } from "../updater-action"

export function QuantCodePreferences() {
  const language = useLanguage()
  const settings = useSettings()
  const platform = usePlatform()
  const updater = useUpdaterAction()
  return <div class="qc-detail-body qc-preferences">
    <h3>桌面偏好</h3>
    <p class="qc-catalog-intro">这些设置只影响本机使用体验。业务组与资源权限由登录身份决定。</p>
    <label class="qc-preference-row"><span>界面语言</span><select class="qc-select-wide" value={language.locale()} onChange={e => language.setLocale(e.currentTarget.value as ReturnType<typeof language.locale>)}>
      <For each={language.locales}>{locale => <option value={locale}>{language.label(locale)}</option>}</For>
    </select></label>
    <label class="qc-preference-row"><span>任务完成通知</span><input type="checkbox" checked={settings.notifications.agent()} onChange={e => settings.notifications.setAgent(e.currentTarget.checked)} /></label>
    <label class="qc-preference-row"><span>权限请求通知</span><input type="checkbox" checked={settings.notifications.permissions()} onChange={e => settings.notifications.setPermissions(e.currentTarget.checked)} /></label>
    <label class="qc-preference-row"><span>错误通知</span><input type="checkbox" checked={settings.notifications.errors()} onChange={e => settings.notifications.setErrors(e.currentTarget.checked)} /></label>
    <Show when={platform.updater}><div class="qc-preference-row"><span>QuantCode {platform.version ? `v${platform.version}` : "桌面端"}</span><button class="qc-button qc-button-secondary" disabled={!updater.action().run} onClick={() => void updater.run()}>{language.t(updater.action().label)}</button></div></Show>
    <details class="qc-shortcut-settings"><summary>键盘快捷键</summary><SettingsKeybinds v2 /></details>
  </div>
}
