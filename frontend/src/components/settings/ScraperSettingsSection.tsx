import { useEffect, useState } from 'react'
import { KeyRound, Sparkles, Wand2 } from 'lucide-react'
import type { AppSettings, LibraryType } from '../../api/types'
import { usePatchSettings, useProviderTest } from '../../api/hooks'
import { Spinner } from '../Spinner'
import { useToast } from '../../store/ui'
import { t } from '../../i18n/zh-CN'
import { Section, Field, TestBadge } from './common'

const typeOrder: LibraryType[] = ['movie', 'tv', 'home', 'course']

export function ScraperSettingsSection({
  settings,
}: {
  settings: AppSettings
}) {
  const patchSettings = usePatchSettings()
  const providerTest = useProviderTest()
  const toast = useToast()

  const [tmdbKey, setTmdbKey] = useState('')
  const [tmdbBase, setTmdbBase] = useState('')
  const [tmdbProxy, setTmdbProxy] = useState('')
  const [tvdbKey, setTvdbKey] = useState('')
  const [tvdbPin, setTvdbPin] = useState('')
  const [tvdbBase, setTvdbBase] = useState('')
  const [tvdbProxy, setTvdbProxy] = useState('')
  const [language, setLanguage] = useState('zh-CN')
  const [seasonType, setSeasonType] = useState('default')
  const [priority, setPriority] = useState<Record<string, string[]>>({
    movie: ['tmdb', 'tvdb'],
    tv: ['tmdb', 'tvdb'],
    home: [],
    course: [],
  })
  const [threshold, setThreshold] = useState('0.75')
  const [refreshDays, setRefreshDays] = useState('30')
  const [testResult, setTestResult] = useState<
    Record<string, { ok: boolean; message: string; latency: number }>
  >({})

  useEffect(() => {
    if (!settings) return
    setTmdbKey(settings.scraper.tmdb.api_key || '')
    setTmdbBase(settings.scraper.tmdb.base_url || '')
    setTmdbProxy(settings.scraper.tmdb.proxy || '')
    setTvdbKey(settings.scraper.tvdb.api_key || '')
    setTvdbPin(settings.scraper.tvdb.pin || '')
    setTvdbBase(settings.scraper.tvdb.base_url || '')
    setTvdbProxy(settings.scraper.tvdb.proxy || '')
    setLanguage(settings.scraper.language || 'zh-CN')
    setSeasonType(settings.scraper.tvdb.season_type || 'default')
    setPriority({
      movie: settings.scraper.provider_priority.movie || [],
      tv: settings.scraper.provider_priority.tv || [],
      home: settings.scraper.provider_priority.home || [],
      course: settings.scraper.provider_priority.course || [],
    })
    setThreshold(String(settings.scraper.match_threshold ?? 0.75))
    setRefreshDays(String(settings.scraper.auto_refresh_days ?? 30))
  }, [settings])

  const save = async (patch: Record<string, unknown>, successTitle = t('settings.saved')) => {
    try {
      await patchSettings.mutateAsync(patch)
      toast({ title: successTitle, tone: 'success' })
      return true
    } catch (error) {
      toast({ title: t('settings.saveFailed'), description: (error as Error).message, tone: 'error' })
      return false
    }
  }

  const saveTmdb = () =>
    save({
      scraper: {
        tmdb: {
          api_key: tmdbKey,
          base_url: tmdbBase || undefined,
          proxy: tmdbProxy,
        },
      },
    })

  const saveTvdb = () =>
    save({
      scraper: {
        tvdb: {
          api_key: tvdbKey,
          pin: tvdbPin,
          base_url: tvdbBase || undefined,
          proxy: tvdbProxy,
          season_type: seasonType,
        },
      },
    })

  const runTest = async (provider: 'tmdb' | 'tvdb') => {
    try {
      const result = await providerTest.mutateAsync(provider)
      setTestResult((prev) => ({
        ...prev,
        [provider]: { ok: result.ok, message: result.message, latency: result.latency_ms },
      }))
    } catch (error) {
      setTestResult((prev) => ({
        ...prev,
        [provider]: { ok: false, message: (error as Error).message, latency: 0 },
      }))
    }
  }

  return (
    <>
      <Section
        id="providers"
        title={t('settings.sections.providers')}
        description={t('settings.providers.keyHidden')}
        icon={KeyRound}
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-[15px] font-semibold text-white">TMDB</h3>
              <span className="chip">默认主源</span>
            </div>
            <Field label={t('settings.providers.tmdbKey')} hint={t('settings.providers.tmdbHint')}>
              <input
                className="input"
                type="password"
                value={tmdbKey}
                onChange={(event) => setTmdbKey(event.target.value)}
                placeholder="未配置"
                autoComplete="off"
              />
            </Field>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label={t('settings.providers.baseUrl')}>
                <input className="input" value={tmdbBase} onChange={(event) => setTmdbBase(event.target.value)} />
              </Field>
              <Field label={t('settings.providers.proxy')}>
                <input
                  className="input"
                  value={tmdbProxy}
                  onChange={(event) => setTmdbProxy(event.target.value)}
                  placeholder={t('settings.providers.proxyPlaceholder')}
                />
              </Field>
            </div>
            <div className="mt-4 flex items-center gap-2">
              <button
                type="button"
                onClick={saveTmdb}
                disabled={patchSettings.isPending}
                className="btn-primary px-5 py-2.5 text-[13px]"
              >
                {t('common.save')}
              </button>
              <button
                type="button"
                onClick={() => runTest('tmdb')}
                disabled={providerTest.isPending}
                className="btn-ghost gap-1.5 px-4 py-2.5 text-[12px]"
              >
                {providerTest.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
                {providerTest.isPending ? t('settings.providers.testing') : t('settings.providers.test')}
              </button>
            </div>
            <TestBadge result={testResult.tmdb} />
          </div>

          <div className="card p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-[15px] font-semibold text-white">TVDB</h3>
              <span className="chip">第二源</span>
            </div>
            <Field label={t('settings.providers.tvdbKey')} hint={t('settings.providers.tvdbHint')}>
              <input
                className="input"
                type="password"
                value={tvdbKey}
                onChange={(event) => setTvdbKey(event.target.value)}
                placeholder="未配置"
                autoComplete="off"
              />
            </Field>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label={t('settings.providers.tvdbPin')}>
                <input
                  className="input"
                  type="password"
                  value={tvdbPin}
                  onChange={(event) => setTvdbPin(event.target.value)}
                  placeholder="可留空"
                  autoComplete="off"
                />
              </Field>
              <Field label={t('settings.providers.baseUrl')}>
                <input className="input" value={tvdbBase} onChange={(event) => setTvdbBase(event.target.value)} />
              </Field>
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label={t('settings.providers.proxy')}>
                <input
                  className="input"
                  value={tvdbProxy}
                  onChange={(event) => setTvdbProxy(event.target.value)}
                  placeholder={t('settings.providers.proxyPlaceholder')}
                />
              </Field>
              <Field label={t('settings.providers.seasonType')}>
                <select
                  className="input"
                  value={seasonType}
                  onChange={(event) => setSeasonType(event.target.value)}
                >
                  <option value="default">{t('library.fields.seasonTypeDefault')}</option>
                  <option value="absolute">{t('library.fields.seasonTypeAbsolute')}</option>
                  <option value="dvd">{t('library.fields.seasonTypeDvd')}</option>
                </select>
              </Field>
            </div>
            <div className="mt-4 flex items-center gap-2">
              <button
                type="button"
                onClick={saveTvdb}
                disabled={patchSettings.isPending}
                className="btn-primary px-5 py-2.5 text-[13px]"
              >
                {t('common.save')}
              </button>
              <button
                type="button"
                onClick={() => runTest('tvdb')}
                disabled={providerTest.isPending}
                className="btn-ghost gap-1.5 px-4 py-2.5 text-[12px]"
              >
                {providerTest.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
                {providerTest.isPending ? t('settings.providers.testing') : t('settings.providers.test')}
              </button>
            </div>
            <TestBadge result={testResult.tvdb} />
          </div>
        </div>

        <div className="card p-5">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t('settings.providers.language')}>
              <select className="input" value={language} onChange={(event) => setLanguage(event.target.value)}>
                <option value="zh-CN">简体中文（zh-CN）</option>
                <option value="zh-TW">繁體中文（zh-TW）</option>
                <option value="en-US">English（en-US）</option>
                <option value="ja-JP">日本語（ja-JP）</option>
              </select>
            </Field>
            <div className="flex items-end">
              <button
                type="button"
                onClick={() => save({ scraper: { language } })}
                disabled={patchSettings.isPending}
                className="btn-ghost w-full justify-center py-3"
              >
                {t('common.save')}
              </button>
            </div>
          </div>
        </div>
      </Section>

      <Section id="matching" title={t('settings.sections.matching')} icon={Wand2}>
        <div className="card p-5">
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label className="label">
                {t('settings.matching.threshold')}
                <span className="ml-2 font-mono text-accent">{Number(threshold).toFixed(2)}</span>
              </label>
              <input
                type="range"
                min="0.5"
                max="0.95"
                step="0.01"
                value={threshold}
                onChange={(event) => setThreshold(event.target.value)}
                className="w-full accent-[#e8b06a]"
              />
              <p className="mt-1.5 text-[11px] text-ink-500">{t('settings.matching.thresholdHint')}</p>
            </div>
            <Field label={t('settings.matching.autoRefreshDays')} hint={t('settings.matching.autoRefreshHint')}>
              <input
                className="input"
                inputMode="numeric"
                value={refreshDays}
                onChange={(event) => setRefreshDays(event.target.value)}
              />
            </Field>
          </div>
          <div className="mt-6 space-y-4">
            <div>
              <label className="label">{t('settings.matching.priority')}</label>
              <p className="mb-3 text-[11px] text-ink-500">{t('settings.matching.priorityHint')}</p>
              <div className="grid gap-3 sm:grid-cols-2">
                {typeOrder.map((type) => (
                  <div key={type} className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
                    <p className="mb-2 text-[12px] font-medium text-ink-200">{t(`library.type.${type}`)}</p>
                    <div className="flex items-center gap-2">
                      {[0, 1].map((index) => (
                        <select
                          key={index}
                          className="input py-1.5 text-[12px]"
                          value={priority[type]?.[index] || ''}
                          onChange={(event) => {
                            const value = event.target.value
                            const next = [...(priority[type] || [])]
                            if (!value) {
                              next.splice(index, 1)
                            } else {
                              next[index] = value
                            }
                            setPriority((prev) => ({
                              ...prev,
                              [type]: next.filter(Boolean),
                            }))
                          }}
                        >
                          <option value="">—</option>
                          <option value="tmdb">TMDB</option>
                          <option value="tvdb">TVDB</option>
                        </select>
                      ))}
                      {priority[type]?.length ? (
                        <span className="text-[10.5px] text-ink-500">
                          {priority[type].join(' → ')}
                        </span>
                      ) : (
                        <span className="text-[10.5px] text-ink-500">不刮削</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="mt-5">
            <button
              type="button"
              onClick={() =>
                save({
                  scraper: {
                    match_threshold: Number(threshold),
                    auto_refresh_days: Number(refreshDays) || 0,
                    provider_priority: priority,
                  },
                })
              }
              disabled={patchSettings.isPending}
              className="btn-primary px-5 py-2.5 text-[13px]"
            >
              {t('settings.matching.save')}
            </button>
          </div>
        </div>
      </Section>
    </>
  )
}
