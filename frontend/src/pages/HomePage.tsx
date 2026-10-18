import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowRight, Library, Sparkles } from 'lucide-react'
import { useHome } from '../api/hooks'
import { HeroCarousel } from '../components/HeroCarousel'
import { ContinueCard } from '../components/PosterCard'
import { PosterRow } from '../components/Row'
import { HeroSkeleton, RowSkeleton } from '../components/Skeleton'
import { EmptyState } from '../components/EmptyState'
import { LoadingBlock } from '../components/Spinner'
import { t } from '../i18n/zh-CN'

function greeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return t('home.greetingMorning')
  if (hour < 18) return t('home.greetingAfternoon')
  return t('home.greetingEvening')
}

export function HomePage() {
  const home = useHome()

  if (home.isLoading) {
    return (
      <div>
        <HeroSkeleton />
        <div className="mx-auto max-w-[1680px] space-y-12 px-5 pt-10 sm:px-10 lg:px-16">
          <RowSkeleton />
          <RowSkeleton />
        </div>
      </div>
    )
  }

  if (home.isError) {
    return (
      <div className="mx-auto max-w-3xl px-5 pt-32">
        <EmptyState
          icon={AlertTriangle}
          title="首页加载失败"
          description={(home.error as Error)?.message}
          action={
            <button type="button" onClick={() => home.refetch()} className="btn-primary">
              {t('common.retry')}
            </button>
          }
        />
      </div>
    )
  }

  const data = home.data
  if (!data) return <LoadingBlock />

  const empty =
    data.stats.movies + data.stats.series + data.stats.videos === 0 &&
    data.rows.length === 0

  return (
    <div className="pb-20">
      {data.hero.length ? (
        <HeroCarousel items={data.hero} />
      ) : (
        <div className="relative flex min-h-[420px] items-end overflow-hidden bg-[radial-gradient(120%_120%_at_20%_0%,rgba(232,176,106,0.16),#07080a_62%)] px-5 pb-16 pt-32 sm:px-10 lg:px-16">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent/80">
              {greeting()}
            </p>
            <h1 className="mt-3 font-display text-4xl font-black tracking-tight text-white sm:text-5xl">
              {t('app.name')}
            </h1>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-ink-300">
              {t('app.tagline')}。{data.stats.movies + data.stats.series} 个条目已入库。
            </p>
          </div>
        </div>
      )}

      <div className="relative z-10 mx-auto -mt-6 max-w-[1680px] space-y-12 px-5 sm:px-10 lg:px-16">
        {data.needs_attention > 0 ? (
          <Link
            to="/fix"
            className="flex items-center gap-3 rounded-2xl border border-amber-400/25 bg-amber-400/[0.08] px-4 py-3 text-sm text-amber-200 transition hover:border-amber-400/40 hover:bg-amber-400/[0.12]"
          >
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span className="flex-1">
              {t('home.needsAttention', { count: data.needs_attention })}
            </span>
            <span className="flex items-center gap-1 text-xs font-medium">
              {t('home.needsAttentionAction')}
              <ArrowRight className="h-3.5 w-3.5" />
            </span>
          </Link>
        ) : null}

        {empty ? (
          <EmptyState
            icon={Library}
            title={t('home.emptyTitle')}
            description={t('home.emptyDesc')}
            action={
              <Link to="/settings" className="btn-primary">
                {t('home.emptyAction')}
              </Link>
            }
            className="mt-8"
          />
        ) : null}

        {data.continue.length ? (
          <PosterRow title={t('home.continue')} items={[]} eyebrow="CONTINUE WATCHING">
            {data.continue.map((item) => (
              <ContinueCard key={`${item.continue_item_id}-${item.progress?.updated_at}`} item={item} />
            ))}
          </PosterRow>
        ) : null}

        {data.rows.map((row, index) => (
          <PosterRow
            key={row.key}
            title={row.title}
            items={row.items}
            eyebrow={index === 0 ? 'JUST ADDED' : undefined}
          />
        ))}

        {!empty ? (
          <div className="flex flex-col items-start justify-between gap-4 border-t border-white/8 pt-8 text-xs text-ink-500 sm:flex-row sm:items-center">
            <p className="flex items-center gap-2">
              <Sparkles className="h-3.5 w-3.5 text-accent/70" />
              {t('home.stats', {
                movies: data.stats.movies,
                series: data.stats.series,
                episodes: data.stats.episodes,
              })}
            </p>
          </div>
        ) : null}
      </div>
    </div>
  )
}
