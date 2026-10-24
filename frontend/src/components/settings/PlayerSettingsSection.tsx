import { useEffect, useState } from 'react'
import { Play } from 'lucide-react'
import type { AppSettings } from '../../api/types'
import { usePatchSettings } from '../../api/hooks'
import { useToast } from '../../store/ui'
import { t } from '../../i18n/zh-CN'
import { Section, Field, headersToText, textToHeaders } from './common'

const MODE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'builtin', label: t('settings.player.builtin') },
  { value: 'copy', label: t('settings.player.copy') },
]

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
  const [cacheLimitMb, setCacheLimitMb] = useState('128')
  const [bufferLimit, setBufferLimit] = useState('')
  const [diskLimit, setDiskLimit] = useState('')
  const [playHeadersGlobal, setPlayHeadersGlobal] = useState('')

  useEffect(() => {
    if (!settings) return
    setPlayerMode(settings.player.mode || 'builtin')
    setProgressInterval(String(settings.player.progress_interval_ms ?? 5000))
    setTokenTtl(String(settings.player.play_token_ttl_hours ?? 12))
    setCacheLimitMb(String(settings.player.cache_limit_mb ?? 128))
    setBufferLimit(settings.player.buffer_limit_mb == null ? '' : String(settings.player.buffer_limit_mb))
    setDiskLimit(settings.player.disk_cache_limit_mb == null ? '' : String(settings.player.disk_cache_limit_mb))
    setPlayHeadersGlobal(headersToText(settings.player.play_headers))
  }, [settings])

  const handleSave = async () => {
    try {
      await patchSettings.mutateAsync({
        player: {
          mode: playerMode,
          progress_interval_ms: Number(progressInterval) || 5000,
          play_token_ttl_hours: Number(tokenTtl) || 12,
          cache_limit_mb: Math.min(Math.max(Number(cacheLimitMb) || 0, 0), 2048),
          buffer_limit_mb: bufferLimit.trim() === '' ? null : Number(bufferLimit),
          disk_cache_limit_mb: diskLimit.trim() === '' ? null : Number(diskLimit),
          play_headers: textToHeaders(playHeadersGlobal),
        },
      })
      toast({ title: t('settings.saved'), tone: 'success' })
    } catch (error) {
      toast({ title: t('settings.saveFailed'), description: (error as Error).message, tone: 'error' })
    }
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
            <select
              className="input"
              value={playerMode}
              onChange={(event) => setPlayerMode(event.target.value)}
            >
              {MODE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
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
          <Field label={t('settings.player.cacheLimit')} hint={t('settings.player.cacheLimitHint')}>
            <input
              className="input"
              inputMode="numeric"
              min={0}
              max={2048}
              value={cacheLimitMb}
              onChange={(event) => setCacheLimitMb(event.target.value)}
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
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="预读容量默认值（MB）" hint="留空使用设备预算；0 关闭预读；本机可覆盖。">
            <input className="input" type="number" min="0" max="8192" value={bufferLimit} onChange={e => setBufferLimit(e.target.value)} placeholder="使用设备预算" />
          </Field>
          <Field label="磁盘缓存默认值（MB）" hint="留空使用设备预算；0 关闭磁盘缓存；退出播放清空。">
            <input className="input" type="number" min="0" max="32768" value={diskLimit} onChange={e => setDiskLimit(e.target.value)} placeholder="使用设备预算" />
          </Field>
        </div>

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
