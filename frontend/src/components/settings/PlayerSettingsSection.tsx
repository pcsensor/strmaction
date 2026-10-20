import { useEffect, useState } from 'react'
import { Play } from 'lucide-react'
import type { AppSettings } from '../../api/types'
import { usePatchSettings } from '../../api/hooks'
import { useToast } from '../../store/ui'
import { t } from '../../i18n/zh-CN'
import { Section, Field, headersToText, textToHeaders } from './common'

export function PlayerSettingsSection({
  settings,
}: {
  settings: AppSettings
}) {
  const patchSettings = usePatchSettings()
  const toast = useToast()

  const [playerMode, setPlayerMode] = useState<string>('builtin')
  const [progressInterval, setProgressInterval] = useState('5000')
  const [tokenTtl, setTokenTtl] = useState('12')
  const [fallbackOnError, setFallbackOnError] = useState(true)
  const [playHeadersGlobal, setPlayHeadersGlobal] = useState('')
  const [mpvPath, setMpvPath] = useState('')
  const [mpvArgs, setMpvArgs] = useState('')
  const [enableProgress, setEnableProgress] = useState(true)

  useEffect(() => {
    if (!settings) return
    setPlayerMode(settings.player.mode || 'builtin')
    setProgressInterval(String(settings.player.progress_interval_ms ?? 5000))
    setTokenTtl(String(settings.player.play_token_ttl_hours ?? 12))
    setFallbackOnError(settings.player.fallback_on_error !== false)
    setPlayHeadersGlobal(headersToText(settings.player.play_headers))
    setMpvPath(settings.player.mpv_path || '')
    setMpvArgs((settings.player.mpv_extra_args || []).join('\n'))
    setEnableProgress(Boolean(settings.player.enable_progress))
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

  const handleSave = () => {
    save({
      player: {
        mode: playerMode,
        progress_interval_ms: Number(progressInterval) || 5000,
        play_token_ttl_hours: Number(tokenTtl) || 12,
        fallback_on_error: fallbackOnError,
        play_headers: textToHeaders(playHeadersGlobal),
        mpv_path: mpvPath,
        mpv_extra_args: mpvArgs.split('\n').map((line) => line.trim()).filter(Boolean),
        enable_progress: enableProgress,
      },
    })
  }

  return (
    <Section
      id="player-global"
      title={t('settings.player.global')}
      description={t('settings.player.globalHint')}
      icon={Play}
    >
      <div className="card p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('settings.player.default')} hint={t('settings.player.modeHint')}>
            <select className="input" value={playerMode} onChange={(event) => setPlayerMode(event.target.value)}>
              <option value="builtin">{t('settings.player.builtin')}</option>
              <option value="external_mpv">{t('settings.player.externalMpv')}</option>
              <option value="browser_intent">{t('settings.player.browserIntent')}</option>
              <option value="desktop_mpv">{t('settings.player.desktopMpv')}</option>
              <option value="copy">{t('settings.player.copy')}</option>
              <option value="auto">{t('settings.player.auto')}</option>
            </select>
          </Field>
          <Field label={t('settings.player.mpvPath')}>
            <input className="input" value={mpvPath} onChange={(event) => setMpvPath(event.target.value)} />
          </Field>
          <Field label={t('settings.player.progressInterval')} hint={t('settings.player.progressIntervalHint')}>
            <input
              className="input"
              inputMode="numeric"
              value={progressInterval}
              onChange={(event) => setProgressInterval(event.target.value)}
            />
          </Field>
          <Field label={t('settings.player.tokenTtl')} hint={t('settings.player.tokenTtlHint')}>
            <input
              className="input"
              inputMode="numeric"
              value={tokenTtl}
              onChange={(event) => setTokenTtl(event.target.value)}
            />
          </Field>
        </div>
        <div className="mt-4">
          <Field label={t('settings.player.headers')} hint={t('settings.player.headersHint')}>
            <textarea
              className="input min-h-[92px] font-mono text-[12px] leading-relaxed"
              value={playHeadersGlobal}
              onChange={(event) => setPlayHeadersGlobal(event.target.value)}
              placeholder={'User-Agent: pan.baidu.com\nReferer: https://pan.baidu.com/'}
            />
          </Field>
        </div>
        <div className="mt-4">
          <Field label={t('settings.player.extraArgs')}>
            <textarea
              className="input min-h-[90px] font-mono text-[12px] leading-relaxed"
              value={mpvArgs}
              onChange={(event) => setMpvArgs(event.target.value)}
            />
          </Field>
        </div>
        <label className="mt-4 flex items-center gap-2.5 text-[12.5px] text-ink-200">
          <input
            type="checkbox"
            checked={fallbackOnError}
            onChange={(event) => setFallbackOnError(event.target.checked)}
            className="h-4 w-4 accent-[#e8b06a]"
          />
          {t('settings.player.fallback')}
        </label>
        <label className="mt-3 flex items-center gap-2.5 text-[12.5px] text-ink-200">
          <input
            type="checkbox"
            checked={enableProgress}
            onChange={(event) => setEnableProgress(event.target.checked)}
            className="h-4 w-4 accent-[#e8b06a]"
          />
          {t('settings.player.enableProgress')}
        </label>

        <div className="mt-5">
          <button
            type="button"
            onClick={handleSave}
            disabled={patchSettings.isPending}
            className="btn-primary px-5 py-2.5 text-[13px]"
          >
            {t('common.save')}
          </button>
        </div>
      </div>
    </Section>
  )
}
