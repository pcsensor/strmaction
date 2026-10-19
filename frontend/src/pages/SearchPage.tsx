import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Search as SearchIcon, X } from 'lucide-react'
import { useSearch } from '../api/hooks'
import { PosterCard } from '../components/PosterCard'
import { EmptyState } from '../components/EmptyState'
import { PosterSkeleton } from '../components/Skeleton'
import { t } from '../i18n/zh-CN'

export function SearchPage() {
  const [params, setParams] = useSearchParams()
  const initialQ = params.get('q') || ''
  const genre = params.get('genre') || undefined
  const [query, setQuery] = useState(initialQ)
  const [debounced, setDebounced] = useState(initialQ)
  const result = useSearch(debounced, genre)

  useEffect(() => {
    setQuery(params.get('q') || '')
    setDebounced(params.get('q') || '')
  }, [params])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(query.trim())
      const next = new URLSearchParams(params)
      if (query.trim()) next.set('q', query.trim())
      else next.delete('q')
      if (query.trim() !== (params.get('q') || '')) {
        setParams(next, { replace: true })
      }
    }, 320)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query])

  const setGenre = (value: string | undefined) => {
    const next = new URLSearchParams(params)
    if (value) next.set('genre', value)
    else next.delete('genre')
    setParams(next, { replace: true })
  }

  const items = result.data?.items ?? []
  const genres = result.data?.genres ?? []
  const total = result.data?.total ?? 0

  return (
    <div className="mx-auto max-w-[1680px] px-5 pb-24 pt-28 sm:px-10 lg:px-16">
      <div className="mx-auto max-w-3xl text-center">
        <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-accent/80">
          DISCOVER
        </p>
        <h1 className="mt-3 font-display text-3xl font-black tracking-tight text-white sm:text-4xl">
          {t('search.title')}
        </h1>
        <div className="relative mt-6">
          <SearchIcon className="pointer-events-none absolute left-5 top-1/2 h-5 w-5 -translate-y-1/2 text-ink-400" />
          <input
            value={query}
            autoFocus
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('search.placeholder')}
            className="input h-14 rounded-full pl-14 pr-14 text-base shadow-[0_20px_60px_-30px_rgba(0,0,0,0.9)]"
            aria-label={t('search.title')}
          />
          {query ? (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label={t('search.clear')}
              className="absolute right-4 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full text-ink-400 transition hover:bg-white/10 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      </div>

      {genres.length ? (
        <div className="no-scrollbar mt-8 flex justify-start gap-2 overflow-x-auto pb-1 sm:justify-center">
          <button
            type="button"
            onClick={() => setGenre(undefined)}
            className={`shrink-0 rounded-full border px-4 py-1.5 text-[12.5px] transition ${
              !genre
                ? 'border-white bg-white text-ink-950'
                : 'border-white/10 bg-white/[0.03] text-ink-300 hover:border-white/25 hover:text-white'
            }`}
          >
            {t('common.all')}
          </button>
          {genres.map((item) => (
            <button
              key={item.name}
              type="button"
              onClick={() => setGenre(item.name === genre ? undefined : item.name)}
              className={`shrink-0 rounded-full border px-4 py-1.5 text-[12.5px] transition ${
                genre === item.name
                  ? 'border-accent/60 bg-accent/15 text-accent'
                  : 'border-white/10 bg-white/[0.03] text-ink-300 hover:border-white/25 hover:text-white'
              }`}
            >
              {item.name}
              <span className="ml-1.5 text-[10px] opacity-50">{item.count}</span>
            </button>
          ))}
        </div>
      ) : null}

      <div className="mt-10">
        {result.isLoading ? (
          <div className="grid grid-cols-3 gap-x-4 gap-y-8 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-7">
            {Array.from({ length: 14 }).map((_, index) => (
              <PosterSkeleton key={index} className="!w-full" />
            ))}
          </div>
        ) : result.isError ? (
          <EmptyState
            title="搜索失败"
            description={(result.error as Error)?.message}
            action={
              <button type="button" onClick={() => result.refetch()} className="btn-primary">
                {t('common.retry')}
              </button>
            }
          />
        ) : items.length ? (
          <>
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-sm font-medium text-ink-300">
                {debounced ? t('search.resultCount', { count: total }) : '高分推荐'}
              </h2>
              {genre ? (
                <button
                  type="button"
                  onClick={() => setGenre(undefined)}
                  className="text-[12px] text-ink-400 transition hover:text-white"
                >
                  清除筛选：{genre}
                </button>
              ) : null}
            </div>
            <div className="grid grid-cols-3 gap-x-4 gap-y-8 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-7">
              {items.map((item) => (
                <PosterCard key={item.id} item={item} width="w-full" className="!w-full" />
              ))}
            </div>
          </>
        ) : (
          <EmptyState
            icon={SearchIcon}
            title={debounced ? t('search.noResult', { query: debounced }) : t('common.empty')}
            description={t('search.emptyHint')}
            action={
              debounced ? (
                <button type="button" onClick={() => setQuery('')} className="btn-ghost">
                  {t('search.clear')}
                </button>
              ) : (
                <Link to="/settings" className="btn-primary">
                  {t('home.emptyAction')}
                </Link>
              )
            }
          />
        )}
      </div>
    </div>
  )
}
