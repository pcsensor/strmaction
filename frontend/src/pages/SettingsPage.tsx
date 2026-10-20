import { AlertTriangle, Database } from 'lucide-react'
import { useAuthState, useLibraries, useSettings } from '../api/hooks'
import { EmptyState } from '../components/EmptyState'
import { t } from '../i18n/zh-CN'
import { LibrarySettingsSection } from '../components/settings/LibrarySettingsSection'
import { ScraperSettingsSection } from '../components/settings/ScraperSettingsSection'
import { PlayerPreferenceSection } from '../components/settings/PlayerPreferenceSection'
import { PlayerSettingsSection } from '../components/settings/PlayerSettingsSection'
import { SecuritySection } from '../components/settings/SecuritySection'
import { SystemSettingsSection } from '../components/settings/SystemSettingsSection'
import { AboutSection } from '../components/settings/AboutSection'

const adminSections = [
  ['libraries', t('settings.sections.libraries')],
  ['providers', t('settings.sections.providers')],
  ['matching', t('settings.sections.matching')],
  ['player', t('settings.sections.player')],
  ['player-global', t('settings.player.globalNav')],
  ['scanner', t('settings.sections.scanner')],
  ['data', t('settings.sections.data')],
  ['security', t('settings.sections.security')],
  ['about', t('settings.sections.about')],
] as const

const userSections = [
  ['player', t('settings.sections.player')],
  ['security', t('settings.sections.security')],
  ['about', t('settings.sections.about')],
] as const

export function SettingsPage() {
  const auth = useAuthState()
  const isAdmin = auth.data?.user?.role === 'admin'

  const settingsQuery = useSettings(isAdmin)
  const librariesQuery = useLibraries(isAdmin)

  const settings = settingsQuery.data?.settings
  const libraries = librariesQuery.data?.libraries ?? []
  const sections = isAdmin ? adminSections : userSections

  if (isAdmin && settingsQuery.isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-5 pt-32">
        <div className="space-y-4">
          <div className="skeleton h-10 w-48 rounded-xl" />
          <div className="skeleton h-40 rounded-2xl" />
          <div className="skeleton h-56 rounded-2xl" />
        </div>
      </div>
    )
  }

  if (isAdmin && !settings) {
    return (
      <div className="mx-auto max-w-2xl px-5 pt-32">
        <EmptyState
          icon={AlertTriangle}
          title="设置加载失败"
          description={(settingsQuery.error as Error)?.message}
          action={
            <button type="button" onClick={() => settingsQuery.refetch()} className="btn-primary">
              {t('common.retry')}
            </button>
          }
        />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl px-5 pb-28 pt-28 sm:px-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-accent/80">
            {isAdmin ? 'CONFIGURATION' : 'PREFERENCES'}
          </p>
          <h1 className="mt-2 font-display text-3xl font-black tracking-tight text-white">
            {t('settings.title')}
          </h1>
          <p className="mt-2 text-[13px] text-ink-400">
            {t(isAdmin ? 'settings.subtitle' : 'settings.subtitleUser')}
          </p>
        </div>
        {isAdmin ? (
          <div className="flex items-center gap-2 text-[11px] text-ink-500">
            <Database className="h-3.5 w-3.5" />
            {settingsQuery.data?.data_dir}
          </div>
        ) : null}
      </div>

      <div className="no-scrollbar sticky top-[68px] z-30 -mx-1 mt-6 flex gap-1 overflow-x-auto border-b border-white/8 bg-[#07080a]/85 px-1 py-2 backdrop-blur-xl">
        {sections.map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            className="shrink-0 rounded-full px-3.5 py-1.5 text-[12px] text-ink-300 transition hover:bg-white/8 hover:text-white"
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-10 space-y-16">
        {isAdmin && settings ? (
          <>
            <LibrarySettingsSection
              libraries={libraries}
              onRefresh={() => librariesQuery.refetch()}
            />
            <ScraperSettingsSection settings={settings} />
            <PlayerPreferenceSection />
            <PlayerSettingsSection settings={settings} />
            <SystemSettingsSection settings={settings} />
            <SecuritySection />
            <AboutSection />
          </>
        ) : (
          <>
            <PlayerPreferenceSection />
            <SecuritySection />
            <AboutSection />
          </>
        )}
      </div>
    </div>
  )
}
