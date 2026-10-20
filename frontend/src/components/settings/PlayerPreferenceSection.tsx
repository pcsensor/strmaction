import { useEffect, useState } from 'react'
import { Play, Tv } from 'lucide-react'
import type { PlayMode } from '../../api/types'
import { useMyPlayer, usePatchMyPlayer } from '../../api/hooks'
import { useToast } from '../../store/ui'
import { t } from '../../i18n/zh-CN'
import { Field, Section } from './common'

const MODE_OPTIONS: Array<{ value: PlayMode | 'auto'; label: string }> = [
  { value: 'auto', label: t('settings.player.auto') },
  { value: 'builtin', label: t('settings.player.builtin') },
  { value: 'external_mpv', label: t('settings.player.externalMpv') },
  { value: 'browser_intent', label: t('settings.player.browserIntent') },
  { value: 'desktop_mpv', label: t('settings.player.desktopMpv') },
  { value: 'copy', label: t('settings.player.copy') },
]

function modeLabel(mode: string | null | undefined): string {
  return MODE_OPTIONS.find((item) => item.value === mode)?.label ?? mode ?? '—'
}

type FallbackChoice = 'inherit' | 'on' | 'off'

/** 所有登录用户都可修改的个人播放偏好；只影响自己。 */
export function PlayerPreferenceSection() {
  const prefsQuery = useMyPlayer()
  const patchPlayer = usePatchMyPlayer()
  const toast = useToast()

  const [mode, setMode] = useState('')
  const [fallback, setFallback] = useState<FallbackChoice>('inherit')

  const data = prefsQuery.data
  const allowedModes = data?.allowed_modes
  const availableModes = data?.available_modes ?? data?.allowed_modes
  const chosenMode = data ? mode || data.defaults.mode : null
  const resolvedMode = data?.resolved_mode ?? data?.effective.mode
  const degraded = Boolean(
    data &&
      chosenMode &&
      chosenMode !== 'auto' &&
      resolvedMode &&
      resolvedMode !== chosenMode,
  )
  const clientName = data?.client?.is_companion
    ? t('settings.player.clientCompanion')
    : data?.client?.is_android
      ? t('settings.player.clientAndroid')
      : t('settings.player.clientDesktop')
  const degradeHint =
    chosenMode === 'builtin' || chosenMode === 'external_mpv'
      ? t('settings.player.needCompanion')
      : chosenMode === 'browser_intent'
        ? t('settings.player.needAndroid')
        : chosenMode === 'desktop_mpv'
          ? t('settings.player.needServerMpv')
          : null
  const companion = typeof window !== 'undefined' ? window.StrmActionNative : undefined
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== 'undefined' && Boolean(window.StrmActionNative?.isDesktop?.()),
  )

  useEffect(() => {
    const update = () =>
      setIsDesktop(
        typeof window !== 'undefined' && Boolean(window.StrmActionNative?.isDesktop?.()),
      )
    update()
    window.addEventListener('strmaction:desktop-ready', update)
    return () => window.removeEventListener('strmaction:desktop-ready', update)
  }, [])

  useEffect(() => {
    if (!data) return
    setMode(data.overrides.mode ?? '')
    setFallback(
      data.overrides.fallback_on_error === null
        ? 'inherit'
        : data.overrides.fallback_on_error
          ? 'on'
          : 'off',
    )
  }, [data])

  const handleSave = async () => {
    try {
      await patchPlayer.mutateAsync({
        mode: mode === '' ? null : (mode as PlayMode | 'auto'),
        fallback_on_error: fallback === 'inherit' ? null : fallback === 'on',
      })
      toast({ title: t('settings.saved'), tone: 'success' })
    } catch (error) {
      toast({
        title: t('settings.saveFailed'),
        description: (error as Error).message,
        tone: 'error',
      })
    }
  }

  return (
    <Section id="player" title={t('settings.player.mine')} icon={Play}>
      <div className="card p-5">
        {isDesktop ? (
          <div className="mb-4 rounded-2xl border border-accent/20 bg-accent/5 p-3 text-[11.5px] leading-relaxed text-ink-300">
            <p>{t('settings.player.desktopNotice')}</p>
            <button
              type="button"
              onClick={() => companion?.openSettings?.()}
              className="btn-ghost mt-2 px-4 py-2 text-[12px]"
            >
              {t('settings.player.desktopSettings')}
            </button>
          </div>
        ) : null}

        {prefsQuery.isLoading ? <div className="skeleton h-28 rounded-xl" /> : null}

        {!prefsQuery.isLoading && !data ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-[12.5px] text-rose-300">
              {t('settings.player.loadFailed')}：{(prefsQuery.error as Error)?.message}
            </span>
            <button
              type="button"
              onClick={() => prefsQuery.refetch()}
              className="btn-ghost px-4 py-2 text-[12px]"
            >
              {t('common.retry')}
            </button>
          </div>
        ) : null}

        {data ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t('settings.player.myMode')} hint={t('settings.player.myHint')}>
                <select
                  className="input"
                  value={mode}
                  onChange={(event) => setMode(event.target.value)}
                >
                  <option value="">
                    {t('settings.player.inherit', { mode: modeLabel(data.defaults.mode) })}
                  </option>
                  {MODE_OPTIONS.filter(
                    (option) => !allowedModes || allowedModes.includes(option.value),
                  ).map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                      {availableModes && !availableModes.includes(option.value)
                        ? ` · ${t('settings.player.unsupportedHere')}`
                        : ''}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('settings.player.fallback')}>
                <select
                  className="input"
                  value={fallback}
                  onChange={(event) => setFallback(event.target.value as FallbackChoice)}
                >
                  <option value="inherit">{t('settings.player.fallbackInherit')}</option>
                  <option value="on">{t('settings.player.fallbackOn')}</option>
                  <option value="off">{t('settings.player.fallbackOff')}</option>
                </select>
              </Field>
            </div>

            <p className="mt-3 text-[11px] leading-relaxed text-ink-500">
              {t('settings.player.modeHint')}
            </p>
            <p className="mt-1.5 text-[11px] leading-relaxed text-ink-500">
              {t('settings.player.clientLabel', { client: clientName })}
              {' · '}
              {t('settings.player.resolvedMode', { mode: modeLabel(resolvedMode) })}
            </p>

            {degraded ? (
              <div className="mt-3 rounded-2xl border border-amber-400/25 bg-amber-400/10 p-3 text-[11.5px] leading-relaxed text-amber-200">
                <p>
                  {t('settings.player.degradeWarning', {
                    mode: modeLabel(resolvedMode),
                  })}
                </p>
                {degradeHint ? <p className="mt-1 text-amber-200/80">{degradeHint}</p> : null}
              </div>
            ) : null}

            <div className="mt-5 rounded-2xl border border-white/8 bg-white/[0.02] p-4">
              <p className="flex items-center gap-2 text-[12.5px] font-medium text-ink-100">
                <Tv className="h-4 w-4 text-accent" />
                {t('settings.player.companion')}
              </p>
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-400">
                {companion?.version?.()
                  ? t('settings.player.companionVersion', { version: companion.version() })
                  : t('settings.player.companionNotInstalled')}
              </p>
              {companion?.openSettings ? (
                <button
                  type="button"
                  onClick={() => companion.openSettings?.()}
                  className="btn-ghost mt-3 px-4 py-2 text-[12px]"
                >
                  {t('settings.player.companionOpen')}
                </button>
              ) : (
                <p className="mt-1.5 text-[11px] text-ink-500">
                  {t('settings.player.companionHint')}
                </p>
              )}
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleSave}
                disabled={patchPlayer.isPending}
                className="btn-primary px-5 py-2.5 text-[13px]"
              >
                {t('common.save')}
              </button>
              <span className="text-[11px] text-ink-500">
                {t('settings.player.effective', {
                  mode: modeLabel(resolvedMode),
                  fallback: data.effective.fallback_on_error
                    ? t('settings.player.fallbackOnShort')
                    : t('settings.player.fallbackOffShort'),
                })}
              </span>
            </div>
          </>
        ) : null}
      </div>
    </Section>
  )
}
