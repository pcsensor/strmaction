import { Link } from 'react-router-dom'
import { Check, Play, Star, X } from 'lucide-react'
import type { ContinueItem, ItemSummary } from '../api/types'
import { ImageWithFallback } from './ImageWithFallback'
import { ProgressBar } from './ProgressBar'
import { useDismissContinue } from '../api/hooks'
import { useStartPlayback } from '../hooks/useStartPlayback'
import { useToast, useUIStore } from '../store/ui'
import { t } from '../i18n/zh-CN'

interface PosterCardProps {
  item: ItemSummary
  className?: string
  width?: string
  showTitle?: boolean
}

export function PosterCard({
  item,
  className = '',
  width = 'w-[142px] sm:w-[160px] lg:w-[176px]',
  showTitle = true,
}: PosterCardProps) {
  const start = useStartPlayback()
  const tvMode = useUIStore((state) => state.tvMode)
  const progress = item.progress?.progress ?? null

  return (
    <Link
      to={`/item/${item.id}`}
      data-focusable
      className={`group block shrink-0 focus-ring ${width} ${className}`}
      aria-label={item.title}
    >
      <div className="poster-card aspect-[2/3] w-full">
        <ImageWithFallback
          src={item.poster}
          alt={item.title}
          color={item.color}
          kind={item.kind}
          imgClassName="transition-transform duration-700 ease-silk group-hover:scale-[1.045]"
        />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/75 via-black/0 to-black/10 opacity-75" />

        <div className="absolute left-2.5 top-2.5 flex flex-col gap-1.5">
          {item.rating ? (
            <span className="flex items-center gap-1 rounded-full bg-black/65 px-2 py-0.5 text-[10px] font-semibold text-amber-300 backdrop-blur">
              <Star className="h-3 w-3 fill-current" />
              {item.rating.toFixed(1)}
            </span>
          ) : null}
          {item.badges?.slice(0, 1).map((badge) => (
            <span
              key={badge}
              className="w-fit rounded bg-black/65 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white/85 backdrop-blur"
            >
              {badge}
            </span>
          ))}
        </div>

        {item.watched ? (
          <span className="absolute right-2.5 top-2.5 grid h-6 w-6 place-items-center rounded-full bg-emerald-500/90 text-white shadow">
            <Check className="h-3.5 w-3.5" strokeWidth={3} />
          </span>
        ) : null}

        {progress !== null && progress > 0 ? (
          <div className="absolute inset-x-2.5 bottom-2.5">
            <ProgressBar value={progress} thin />
          </div>
        ) : null}

        <button
          type="button"
          aria-label={t('common.play')}
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            start(item.id)
          }}
          className={`absolute inset-0 m-auto grid h-12 w-12 place-items-center rounded-full bg-white/92 text-ink-950 shadow-lift transition-all duration-300 ${
            tvMode
              ? 'opacity-0 focus-visible:opacity-100'
              : 'scale-90 opacity-0 group-hover:scale-100 group-hover:opacity-100'
          }`}
        >
          <Play className="ml-0.5 h-5 w-5 fill-current" />
        </button>
      </div>

      {showTitle ? (
        <div className="mt-2.5 px-0.5">
          <h3 className="line-clamp-1 text-[13.5px] font-medium text-ink-100 transition group-hover:text-white">
            {item.title}
          </h3>
          <p className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-ink-400">
            {item.kind === 'folder' ? <span>文件夹</span> : null}
            {item.year ? <span>{item.year}</span> : null}
            {item.kind === 'series' && item.season_no ? (
              <>
                <span className="text-ink-600">·</span>
                <span>{t('detail.seasonN', { n: item.season_no })}</span>
              </>
            ) : null}
            {!item.year && item.kind === 'video' ? <span>{t('library.type.home')}</span> : null}
          </p>
        </div>
      ) : null}
    </Link>
  )
}

export function ContinueCard({ item }: { item: ContinueItem }) {
  const start = useStartPlayback()
  const dismissMutation = useDismissContinue()
  const toast = useToast()
  const progress = item.progress?.progress ?? 0

  const handleDismiss = (event: React.MouseEvent) => {
    event.preventDefault()
    event.stopPropagation()
    dismissMutation.mutate(item.continue_item_id, {
      onSuccess: () => {
        toast({ title: t('home.dismissedToast'), tone: 'success' })
      },
      onError: (err) => {
        toast({ title: t('common.failed'), description: (err as Error).message, tone: 'error' })
      },
    })
  }

  return (
    <div className="group relative w-[280px] shrink-0 overflow-hidden rounded-2xl border border-white/8 bg-ink-850 shadow-card transition duration-300 hover:-translate-y-1 hover:border-white/15 sm:w-[320px]">
      <Link to={`/item/${item.continue_item_id}`} className="block focus-ring rounded-2xl">
        <div className="relative aspect-video">
          <ImageWithFallback
            src={item.backdrop || item.poster}
            alt={item.title}
            color={item.color}
            imgClassName="transition-transform duration-700 ease-silk group-hover:scale-[1.04]"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/25 to-black/10" />
          <div className="absolute inset-x-4 bottom-3">
            <p className="line-clamp-1 text-[14px] font-semibold text-white">{item.title}</p>
            <p className="mt-0.5 line-clamp-1 text-[11.5px] text-white/65">{item.subtitle}</p>
            <ProgressBar value={progress} className="mt-2" trackClassName="bg-white/20" />
          </div>
          <button
            type="button"
            aria-label={t('home.dismissContinue')}
            title={t('home.dismissContinue')}
            onClick={handleDismiss}
            className="absolute right-2.5 top-2.5 z-20 grid h-7 w-7 place-items-center rounded-full bg-black/60 text-white/85 backdrop-blur-md transition duration-200 hover:scale-110 hover:bg-black/90 hover:text-white focus-ring opacity-90 sm:opacity-0 sm:group-hover:opacity-100"
          >
            <X className="h-3.5 w-3.5 stroke-[2.5]" />
          </button>
          <button
            type="button"
            aria-label={t('common.resume')}
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              start(item.continue_item_id)
            }}
            className="absolute inset-0 m-auto grid h-11 w-11 place-items-center rounded-full bg-white/92 text-ink-950 shadow-lift scale-90 opacity-0 transition-all duration-300 group-hover:scale-100 group-hover:opacity-100"
          >
            <Play className="ml-0.5 h-4 w-4 fill-current" />
          </button>
        </div>
      </Link>
    </div>
  )
}
