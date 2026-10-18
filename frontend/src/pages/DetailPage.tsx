import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronRight,
  CircleCheck,
  CircleDashed,
  Clapperboard,
  Edit3,
  ExternalLink,
  ImagePlus,
  Info,
  MonitorPlay,
  Play,
  RefreshCw,
  Search,
  Star,
  Trash2,
  Unlink,
  Upload,
} from 'lucide-react'
import type { CastMember, ItemDetail } from '../api/types'
import {
  useItem,
  useMarkWatched,
  useRefreshItem,
  useUnlockItem,
  useUnmatchItem,
  useUploadPoster,
} from '../api/hooks'
import { DetailSkeleton, RowSkeleton } from '../components/Skeleton'
import { EmptyState } from '../components/EmptyState'
import { CastRow } from '../components/CastRow'
import { EpisodeCard } from '../components/EpisodeCard'
import { ImageWithFallback } from '../components/ImageWithFallback'
import { ProgressBar } from '../components/ProgressBar'
import { MatchDialog } from '../components/MatchDialog'
import { EditDialog } from '../components/EditDialog'
import { useStartPlayback } from '../hooks/useStartPlayback'
import { useToast } from '../store/ui'
import { formatDuration, formatMinutes, formatRelative } from '../utils/format'
import { t } from '../i18n/zh-CN'

const providerLabel: Record<string, string> = {
  tmdb: 'TMDB',
  tvdb: 'TVDB',
  nfo: 'NFO',
}

function stateTone(state: string): string {
  switch (state) {
    case 'failed':
      return 'border-rose-400/30 bg-rose-400/10 text-rose-200'
    case 'pending':
      return 'border-amber-400/30 bg-amber-400/10 text-amber-200'
    case 'manual':
      return 'border-sky-400/30 bg-sky-400/10 text-sky-200'
    default:
      return 'border-white/12 bg-white/5 text-ink-300'
  }
}

function MetaDot() {
  return <span className="text-white/20">·</span>
}

export function DetailPage() {
  const params = useParams()
  const itemId = Number(params.id)
  const query = useItem(Number.isFinite(itemId) ? itemId : null)
  const navigate = useNavigate()
  const start = useStartPlayback()
  const toast = useToast()
  const markWatched = useMarkWatched()
  const refresh = useRefreshItem()
  const unlock = useUnlockItem()
  const unmatch = useUnmatchItem()
  const upload = useUploadPoster()

  const [activeSeason, setActiveSeason] = useState<number | null>(null)
  const [selectedFile, setSelectedFile] = useState<number | null>(null)
  const [matchOpen, setMatchOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const posterInput = useRef<HTMLInputElement | null>(null)
  const backdropInput = useRef<HTMLInputElement | null>(null)

  const data = query.data
  const item = data?.item
  const series = data?.series
  const parent = data?.parent
  const display = item ? (item.kind === 'episode' || item.kind === 'season' ? series || item : item) : null

  useEffect(() => {
    if (!data) return
    setSelectedFile(null)
    if (data.seasons.length) {
      const withProgress = data.seasons.find((season) =>
        season.episodes.some(
          (episode) =>
            episode.progress && !episode.progress.finished && episode.progress.position_ms > 0,
        ),
      )
      setActiveSeason(withProgress?.id ?? data.seasons[0].id)
    }
  }, [data])

  useEffect(() => {
    if (!menuOpen) return
    const close = () => setMenuOpen(false)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menuOpen])

  if (query.isLoading) return <DetailSkeleton />
  if (query.isError || !data || !item) {
    return (
      <div className="mx-auto max-w-2xl px-5 pt-32">
        <EmptyState
          icon={Clapperboard}
          title="找不到这个条目"
          description="它可能已被移除，或者链接不正确。"
          action={
            <button type="button" onClick={() => navigate(-1)} className="btn-primary">
              {t('common.back')}
            </button>
          }
        />
      </div>
    )
  }

  const backdrop =
    item.backdrop_large ||
    series?.backdrop_large ||
    item.backdrop ||
    series?.backdrop ||
    parent?.backdrop_large ||
    null
  const poster = item.poster_large || series?.poster_large || item.poster
  const accent = item.color || series?.color || '#e8b06a'
  const currentSeason = data.seasons.find((season) => season.id === activeSeason) || data.seasons[0]
  const playTarget = item.play_target_id ?? item.id
  const progress = data.progress
  const canResume = Boolean(progress && !progress.finished && progress.position_ms > 2000)
  const mediaFiles = data.media_files.filter((file) => !file.missing)
  const selectedMedia = mediaFiles.find((file) => file.id === selectedFile) || mediaFiles[0]
  const isEpisode = item.kind === 'episode'
  const isSeason = item.kind === 'season'
  const isSeries = item.kind === 'series'
  const cast = (item.cast || []) as CastMember[]
  const provider = item.provider ? providerLabel[item.provider] || item.provider : null
  const title = display?.title || item.title
  const hasAttention =
    (item.kind === 'movie' || item.kind === 'series') &&
    (item.match_state === 'failed' || item.match_state === 'pending')
  const itemCode =
    item.season_no !== null && item.episode_no !== null
      ? `S${String(item.season_no).padStart(2, '0')}E${String(item.episode_no).padStart(2, '0')}`
      : null
  const allWatched = isSeries
    ? Boolean(
        item.series_progress &&
          item.series_progress.total > 0 &&
          item.series_progress.watched >= item.series_progress.total,
      )
    : item.watched
  const seriesStarted = Boolean(item.series_progress && item.series_progress.watched > 0)

  const play = () => start(playTarget, { mediaFileId: selectedMedia?.id })
  const playExternal = () =>
    start(playTarget, { mediaFileId: selectedMedia?.id, mode: 'external' })
  const toggleWatched = async () => {
    const target = isSeries || isSeason ? item.id : playTarget
    if (!target) return
    await markWatched.mutateAsync({ itemId: target, finished: !allWatched })
    toast({ title: allWatched ? t('detail.markedUnwatched') : t('detail.markedWatched'), tone: 'success' })
    query.refetch()
  }

  const onUpload = async (file: File | undefined, kind: 'poster' | 'backdrop') => {
    if (!file) return
    try {
      await upload.mutateAsync({ id: item.id, file, kind })
      toast({ title: t('toast.uploadSuccess'), tone: 'success' })
      query.refetch()
    } catch (error) {
      toast({ title: t('toast.uploadFailed'), description: (error as Error).message, tone: 'error' })
    }
  }

  return (
    <div
      className="relative min-h-screen pb-24"
      style={{ ['--accent' as string]: accent } as React.CSSProperties}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[62vh] overflow-hidden sm:h-[76vh] lg:h-[86vh]">
        {backdrop ? (
          <img
            src={backdrop}
            alt=""
            aria-hidden
            className="h-full w-full scale-105 object-cover opacity-60 blur-[2px]"
          />
        ) : (
          <div className="h-full w-full bg-[radial-gradient(90%_90%_at_45%_0%,rgba(232,176,106,0.16),#07080a_70%)]" />
        )}
        <div className="detail-mask absolute inset-0" />
        <div
          className="absolute inset-0 opacity-40"
          style={{
            background: `radial-gradient(60% 50% at 50% 10%, color-mix(in oklab, ${accent} 22%, transparent), transparent 70%)`,
          }}
        />
      </div>

      <div className="mx-auto max-w-[1680px] px-5 pt-24 sm:px-10 lg:px-16">
        <div className="mb-6 flex items-center gap-2 text-[12px] text-ink-400">
          <button
            type="button"
            onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/'))}
            className="flex items-center gap-1.5 rounded-full border border-white/10 bg-black/25 px-3 py-1.5 transition hover:border-white/25 hover:text-white"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t('common.back')}
          </button>
          {series && series.id !== item.id ? (
            <>
              <Link to={`/item/${series.id}`} className="hover:text-white">
                {series.title}
              </Link>
              <ChevronRight className="h-3 w-3 text-ink-600" />
              <span className="text-ink-300">
                {itemCode || item.title}
              </span>
            </>
          ) : null}
        </div>

        {hasAttention ? (
          <div className="mb-5 flex flex-wrap items-center gap-3 rounded-2xl border border-amber-400/25 bg-amber-400/[0.08] px-4 py-3 text-[13px] text-amber-200">
            <AlertTriangle className="h-4 w-4" />
            <span className="flex-1">{t('detail.neesAttention')}</span>
            <button
              type="button"
              onClick={() => setMatchOpen(true)}
              className="rounded-full border border-amber-300/40 px-3 py-1 text-xs font-medium transition hover:bg-amber-400/15"
            >
              {t('detail.rematch')}
            </button>
          </div>
        ) : null}

        <div className="flex flex-col gap-8 md:flex-row md:gap-10">
          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="w-[152px] shrink-0 sm:w-[200px] md:w-[236px]"
          >
            <div className="poster-card aspect-[2/3] w-full">
              <ImageWithFallback src={poster} alt={title} color={accent} eager />
            </div>
            {data.media_files.length && item.kind !== 'movie' ? (
              <div className="mt-4 hidden md:block">
                <label className="label">{t('detail.versions')}</label>
                {mediaFiles.length > 1 ? (
                  <select
                    value={selectedMedia?.id ?? ''}
                    onChange={(event) => setSelectedFile(Number(event.target.value))}
                    className="input py-2 text-[12.5px]"
                  >
                    {mediaFiles.map((file) => (
                      <option key={file.id} value={file.id}>
                        {file.version || t('detail.defaultVersion')}
                        {file.labels.length ? ` · ${file.labels.join(' ')}` : ''}
                      </option>
                    ))}
                  </select>
                ) : (
                  <p className="text-[12px] text-ink-400">
                    {selectedMedia?.version || t('detail.files', { count: data.media_files.length })}
                  </p>
                )}
              </div>
            ) : null}
          </motion.div>

          <div className="min-w-0 flex-1">
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.55, delay: 0.05, ease: [0.22, 1, 0.36, 1] }}
            >
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {item.kind !== 'episode' &&
                item.match_state !== 'auto' &&
                item.match_state !== 'manual' &&
                !(item.match_state === 'skipped' && provider) ? (
                  <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-medium ${stateTone(item.match_state)}`}>
                    {t(`detail.matchState.${item.match_state}`)}
                  </span>
                ) : null}
                {provider ? (
                  <span className="chip bg-black/30">{provider}</span>
                ) : item.kind !== 'episode' ? (
                  <span className="chip bg-black/30">{t('detail.matchState.skipped')}</span>
                ) : null}
                {item.status ? <span className="chip bg-black/30">{item.status}</span> : null}
                {item.certification ? (
                  <span className="rounded border border-white/25 px-1.5 py-0.5 text-[10px] font-semibold text-white/75">
                    {item.certification}
                  </span>
                ) : null}
              </div>

              {item.logo ? (
                <img
                  src={item.logo}
                  alt={title}
                  className="mb-2 max-h-[104px] w-auto max-w-[min(460px,80%)] object-contain drop-shadow-[0_10px_30px_rgba(0,0,0,0.6)]"
                />
              ) : (
                <h1 className="font-display text-[30px] font-black leading-tight tracking-tight text-white sm:text-[42px]">
                  {isEpisode ? item.title : title}
                </h1>
              )}
              {isEpisode ? (
                <p className="mt-1.5 text-[14px] text-ink-300">
                  <Link to={`/item/${series?.id}`} className="hover:text-white">
                    {series?.title}
                  </Link>
                  <MetaDot />
                  <span className="text-accent">{itemCode}</span>
                </p>
              ) : item.original_title && item.original_title !== item.title ? (
                <p className="mt-2 text-[15px] text-ink-300">{item.original_title}</p>
              ) : null}

              <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px] text-ink-300">
                {display?.year ? <span>{display.year}</span> : null}
                {item.rating ? (
                  <span className="flex items-center gap-1 font-semibold text-amber-300">
                    <Star className="h-3.5 w-3.5 fill-current" />
                    {item.rating.toFixed(1)}
                  </span>
                ) : null}
                {item.runtime_min ? <span>{formatMinutes(item.runtime_min)}</span> : null}
                {isSeries && data.seasons.length ? (
                  <span>{data.seasons.length} 季 · {data.seasons.reduce((sum, s) => sum + s.episode_count, 0)} 集</span>
                ) : null}
                {isEpisode && parent ? <span>{parent.title}</span> : null}
                {item.provider ? <span className="text-ink-500">来源 {provider}</span> : null}
              </div>

              {item.genres.length ? (
                <div className="mt-3.5 flex flex-wrap gap-1.5">
                  {item.genres.map((genre) => (
                    <Link
                      key={genre}
                      to={`/search?genre=${encodeURIComponent(genre)}`}
                      className="chip transition hover:border-accent/40 hover:text-white"
                    >
                      {genre}
                    </Link>
                  ))}
                </div>
              ) : null}

              {isSeries && item.series_progress ? (
                <div className="mt-5 max-w-md">
                  <div className="mb-1.5 flex items-center justify-between text-[11.5px] text-ink-400">
                    <span>
                      {t('detail.seriesProgress', {
                        watched: item.series_progress.watched,
                        total: item.series_progress.total,
                      })}
                    </span>
                    <span>{Math.round(item.series_progress.ratio * 100)}%</span>
                  </div>
                  <ProgressBar value={item.series_progress.ratio} />
                </div>
              ) : canResume && progress ? (
                <div className="mt-5 max-w-md">
                  <div className="mb-1.5 flex items-center justify-between text-[11.5px] text-ink-400">
                    <span>
                      上次看到 {formatDuration(progress.position_ms)}
                      {progress.duration_ms ? ` / ${formatDuration(progress.duration_ms)}` : ''}
                    </span>
                    <span>{formatRelative(progress.updated_at)}</span>
                  </div>
                  <ProgressBar value={progress.progress} />
                </div>
              ) : null}

              <p className="mt-5 max-w-3xl whitespace-pre-line text-[14px] leading-[1.85] text-ink-200/90">
                {item.overview || t('detail.noOverview')}
              </p>

              <div className="mt-7 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={play}
                  className="btn-primary gap-2 px-7 py-3.5 text-[15px] shadow-[0_18px_50px_-18px_rgba(255,255,255,0.45)]"
                >
                  <Play className="h-4.5 w-4.5 fill-current" />
                  {canResume || seriesStarted ? t('detail.resume') : t('detail.play')}
                </button>
                {item.trailer_key ? (
                  <a
                    href={`https://www.youtube.com/watch?v=${item.trailer_key}`}
                    target="_blank"
                    rel="noreferrer"
                    className="btn-ghost gap-2 px-5 py-3.5"
                  >
                    <ExternalLink className="h-4 w-4" />
                    {t('detail.trailer')}
                  </a>
                ) : null}
                <button
                  type="button"
                  onClick={toggleWatched}
                  disabled={markWatched.isPending}
                  className="btn-ghost gap-2 px-5 py-3.5"
                >
                  {allWatched ? <CircleCheck className="h-4 w-4 text-emerald-400" /> : <CircleDashed className="h-4 w-4" />}
                  {allWatched ? t('common.markUnwatched') : t('common.markWatched')}
                </button>

                <div className="relative">
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation()
                      setMenuOpen((value) => !value)
                    }}
                    className="btn-ghost gap-2 px-5 py-3.5"
                  >
                    <Edit3 className="h-4 w-4" />
                    管理
                  </button>
                  {menuOpen ? (
                    <div
                      className="absolute left-0 top-[calc(100%+8px)] z-30 w-56 overflow-hidden rounded-2xl border border-white/10 bg-[#0e1219]/97 p-1.5 shadow-lift backdrop-blur-xl"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {typeof window !== 'undefined' && window.StrmActionNative?.playExternal ? (
                        <MenuButton
                          icon={MonitorPlay}
                          label={t('detail.playExternal')}
                          onClick={() => {
                            setMenuOpen(false)
                            void playExternal()
                          }}
                        />
                      ) : null}
                      <MenuButton
                        icon={Search}
                        label={t('detail.rematch')}
                        onClick={() => {
                          setMenuOpen(false)
                          setMatchOpen(true)
                        }}
                      />
                      <MenuButton
                        icon={RefreshCw}
                        label={t('detail.refreshMeta')}
                        onClick={async () => {
                          setMenuOpen(false)
                          await refresh.mutateAsync(item.id)
                          toast({ title: t('toast.refreshStarted'), description: '可在任务页查看进度', tone: 'success' })
                        }}
                      />
                      <MenuButton
                        icon={Edit3}
                        label={t('detail.editFields')}
                        onClick={() => {
                          setMenuOpen(false)
                          setEditOpen(true)
                        }}
                      />
                      {item.locked_fields.length ? (
                        <MenuButton
                          icon={RefreshCw}
                          label={t('detail.restoreAuto')}
                          onClick={async () => {
                            setMenuOpen(false)
                            await unlock.mutateAsync(item.id)
                            await refresh.mutateAsync(item.id)
                            toast({ title: t('detail.restoredAuto'), tone: 'success' })
                            query.refetch()
                          }}
                        />
                      ) : null}                      <MenuButton
                        icon={ImagePlus}
                        label={t('detail.uploadPoster')}
                        onClick={() => {
                          setMenuOpen(false)
                          posterInput.current?.click()
                        }}
                      />
                      <MenuButton
                        icon={Upload}
                        label={t('detail.uploadBackdrop')}
                        onClick={() => {
                          setMenuOpen(false)
                          backdropInput.current?.click()
                        }}
                      />
                      {item.match_state === 'manual' ? (
                        <MenuButton
                          icon={Unlink}
                          label={t('detail.unmatch')}
                          danger
                          onClick={async () => {
                            setMenuOpen(false)
                            await unmatch.mutateAsync(item.id)
                            toast({ title: t('toast.unmatchDone') })
                            query.refetch()
                          }}
                        />
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </div>

              {item.locked_fields.length ? (
                <p className="mt-4 flex items-center gap-1.5 text-[11px] text-ink-500">
                  <Info className="h-3.5 w-3.5" />
                  {t('detail.lockedHint', { count: item.locked_fields.length })}
                </p>
              ) : null}
              <p className="mt-2 max-w-xl text-[11px] leading-relaxed text-ink-500">
                {t('detail.playHint')}
              </p>

              <input
                ref={posterInput}
                type="file"
                accept="image/*"
                hidden
                onChange={(event) => onUpload(event.target.files?.[0], 'poster')}
              />
              <input
                ref={backdropInput}
                type="file"
                accept="image/*"
                hidden
                onChange={(event) => onUpload(event.target.files?.[0], 'backdrop')}
              />
            </motion.div>
          </div>
        </div>

        <div className="mt-14 space-y-14">
          {isSeries || isSeason ? (
            <section>
              <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
                <h2 className="section-title">{t('detail.seasons')}</h2>
                {data.seasons.length > 1 ? (
                  <div className="no-scrollbar flex max-w-full gap-1.5 overflow-x-auto rounded-full border border-white/10 bg-white/[0.03] p-1">
                    {data.seasons.map((season) => (
                      <button
                        key={season.id}
                        type="button"
                        onClick={() => setActiveSeason(season.id)}
                        className={`shrink-0 rounded-full px-4 py-1.5 text-[12px] font-medium transition ${
                          currentSeason?.id === season.id
                            ? 'bg-white text-ink-950'
                            : 'text-ink-300 hover:text-white'
                        }`}
                      >
                        {season.title || t('detail.seasonN', { n: season.season_no ?? 0 })}
                        <span className="ml-1 text-[10px] opacity-60">{season.episode_count}</span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
              {currentSeason?.episodes.length ? (
                <div className="grid gap-2.5 lg:grid-cols-2">
                  {currentSeason.episodes.map((episode) => (
                    <EpisodeCard
                      key={episode.id}
                      episode={episode}
                      active={episode.id === item.id}
                      posterFallback={display?.poster_large}
                      color={accent}
                    />
                  ))}
                </div>
              ) : (
                <p className="rounded-2xl border border-white/8 bg-white/[0.02] px-5 py-10 text-center text-sm text-ink-400">
                  {t('detail.noEpisodes')}
                </p>
              )}
            </section>
          ) : null}

          {isEpisode && (data.next_episode_id || data.prev_episode_id) ? (
            <div className="flex flex-wrap gap-3">
              {data.prev_episode_id ? (
                <Link to={`/item/${data.prev_episode_id}`} className="btn-ghost">
                  上一集
                </Link>
              ) : null}
              {data.next_episode_id ? (
                <Link to={`/item/${data.next_episode_id}`} className="btn-ghost">
                  下一集
                  <ChevronRight className="h-4 w-4" />
                </Link>
              ) : null}
            </div>
          ) : null}

          {item.kind === 'movie' && data.media_files.length ? (
            <section>
              <h2 className="section-title mb-4">{t('detail.versions')}</h2>
              <div className="flex flex-wrap gap-2">
                {data.media_files.map((file) => (
                  <button
                    key={file.id}
                    type="button"
                    onClick={() => setSelectedFile(file.id)}
                    className={`rounded-xl border px-4 py-2.5 text-left text-[12.5px] transition ${
                      selectedMedia?.id === file.id
                        ? 'border-accent/50 bg-accent/10 text-white'
                        : 'border-white/10 bg-white/[0.03] text-ink-300 hover:border-white/25'
                    }`}
                  >
                    <span className="font-medium">{file.version || t('detail.defaultVersion')}</span>
                    {file.labels.length ? (
                      <span className="ml-2 text-[10px] text-accent/80">{file.labels.join(' · ')}</span>
                    ) : null}
                    {file.missing ? <span className="ml-2 text-[10px] text-rose-300">缺失</span> : null}
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          {cast.length ? <CastRow cast={cast} /> : null}

          {item.collection?.name ? (
            <section>
              <h2 className="section-title mb-4">{t('detail.collection')}</h2>
              <span className="chip">{item.collection.name}</span>
            </section>
          ) : null}
        </div>
      </div>

      <MatchDialog
        open={matchOpen}
        item={item}
        defaultQuery={item.original_title || item.title}
        onClose={() => {
          setMatchOpen(false)
          query.refetch()
        }}
      />
      <EditDialog open={editOpen} item={item} onClose={() => setEditOpen(false)} />
    </div>
  )
}

function MenuButton({
  icon: Icon,
  label,
  onClick,
  danger,
}: {
  icon: typeof Search
  label: string
  onClick: () => void
  danger?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-[12.5px] transition ${
        danger
          ? 'text-rose-300 hover:bg-rose-400/10'
          : 'text-ink-200 hover:bg-white/8 hover:text-white'
      }`}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  )
}
