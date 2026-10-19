import { Link } from 'react-router-dom'
import { Check, Play } from 'lucide-react'
import type { EpisodeSummary } from '../api/types'
import { ImageWithFallback } from './ImageWithFallback'
import { ProgressBar } from './ProgressBar'
import { useStartPlayback } from '../hooks/useStartPlayback'
import { t } from '../i18n/zh-CN'

interface Props {
  episode: EpisodeSummary
  active?: boolean
  posterFallback?: string | null
  color?: string | null
}

export function EpisodeCard({ episode, active = false, posterFallback, color }: Props) {
  const start = useStartPlayback()
  const progress = episode.progress?.progress ?? 0
  const isPlainVideo = (episode as any).kind === 'video' || episode.episode_no == null
  const code = isPlainVideo
    ? ''
    : episode.episode_code || (episode.episode_no ? `E${String(episode.episode_no).padStart(2, '0')}` : '')
  const episodeLabel = isPlainVideo || !episode.episode_no ? '' : `第${episode.episode_no}集`
  const title = (() => {
    if (!episode.title) return episodeLabel || t('detail.episodeN', { n: episode.episode_no ?? '' })
    if (isPlainVideo || !episodeLabel || /第\s*\d+\s*[集话]/.test(episode.title)) return episode.title
    return `${episodeLabel} · ${episode.title}`
  })()

  return (
    <Link
      to={`/item/${episode.id}`}
      data-focusable
      className={`group relative flex gap-3.5 rounded-2xl border p-2.5 transition duration-300 focus-ring ${
        active
          ? 'border-accent/45 bg-accent/[0.07]'
          : 'border-white/8 bg-white/[0.025] hover:border-white/16 hover:bg-white/[0.05]'
      }`}
    >
      <div className="relative aspect-video w-[142px] shrink-0 overflow-hidden rounded-xl sm:w-[168px]">
        <ImageWithFallback
          src={episode.still || posterFallback}
          alt={episode.title}
          color={color}
          imgClassName="transition-transform duration-500 group-hover:scale-[1.04]"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
        {code ? (
          <span className="absolute left-2 top-2 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white/90 backdrop-blur">
            {code}
          </span>
        ) : null}
        {episode.watched ? (
          <span className="absolute right-2 top-2 grid h-5 w-5 place-items-center rounded-full bg-emerald-500/90 text-white">
            <Check className="h-3 w-3" strokeWidth={3} />
          </span>
        ) : null}
        <button
          type="button"
          aria-label={t('common.play')}
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            start(episode.id)
          }}
          className="absolute inset-0 m-auto grid h-9 w-9 place-items-center rounded-full bg-white/90 text-ink-950 opacity-0 shadow transition group-hover:opacity-100"
        >
          <Play className="ml-0.5 h-4 w-4 fill-current" />
        </button>
        {progress > 0 ? (
          <div className="absolute inset-x-2 bottom-2">
            <ProgressBar value={progress} thin />
          </div>
        ) : null}
      </div>

      <div className="min-w-0 flex-1 py-1 pr-1">
        <div className="flex items-start justify-between gap-2">
          <h3 className="line-clamp-1 text-[13.5px] font-medium text-ink-100">
            {title}
          </h3>
          {episode.runtime_min ? (
            <span className="shrink-0 text-[10.5px] text-ink-500">{episode.runtime_min} 分钟</span>
          ) : null}
        </div>
        <p className="mt-1.5 line-clamp-2 text-[11.5px] leading-relaxed text-ink-400">
          {episode.overview || '暂无简介'}
        </p>
        {progress > 0 ? (
          <p className="mt-2 text-[10.5px] text-accent/85">
            {t('detail.episodeProgress', {
              time: `${Math.round((episode.progress?.position_ms || 0) / 60000)} 分钟`,
            })}
          </p>
        ) : null}
      </div>
    </Link>
  )
}
