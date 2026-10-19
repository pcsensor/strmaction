import { useEffect, useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import type { Candidate, ItemDetail } from '../api/types'
import { useCandidates, useMatchItem } from '../api/hooks'
import { Modal } from './Modal'
import { Spinner } from './Spinner'
import { ImageWithFallback } from './ImageWithFallback'
import { useToast } from '../store/ui'
import { t } from '../i18n/zh-CN'

interface Props {
  open: boolean
  item: ItemDetail | null
  defaultQuery: string
  onClose: () => void
}

export function MatchDialog({ open, item, defaultQuery, onClose }: Props) {
  const [provider, setProvider] = useState<'tmdb' | 'tvdb'>('tmdb')
  const [query, setQuery] = useState(defaultQuery)
  const [debounced, setDebounced] = useState(defaultQuery)
  const [manualId, setManualId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const candidates = useCandidates(item?.id ?? null, debounced, provider, open)
  const match = useMatchItem()
  const toast = useToast()

  useEffect(() => {
    if (open) {
      setQuery(defaultQuery)
      setDebounced(defaultQuery)
      setError(null)
      setManualId('')
    }
  }, [defaultQuery, open])

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 380)
    return () => window.clearTimeout(timer)
  }, [query])

  const list: Candidate[] = useMemo(
    () => candidates.data?.candidates ?? [],
    [candidates.data],
  )

  const bind = async (candidateProvider: string, providerId: string) => {
    if (!item) return
    setError(null)
    try {
      await match.mutateAsync({ id: item.id, provider: candidateProvider, providerId })
      toast({ title: t('toast.saved'), description: '元数据已更新', tone: 'success' })
      onClose()
    } catch (err) {
      setError((err as Error).message || t('detail.rematchDialog.failed'))
    }
  }

  const bindManual = () => {
    const value = manualId.trim()
    const matchResult = value.match(/^(tmdb|tvdb|imdb)\s*[:：\-\s]\s*(.+)$/i)
    if (!matchResult) {
      setError(t('detail.rematchDialog.idFormat'))
      return
    }
    let providerName = matchResult[1].toLowerCase()
    let providerId = matchResult[2].trim()
    if (providerName === 'imdb' && !providerId.startsWith('tt')) providerId = `tt${providerId}`
    if (providerName === 'imdb') providerName = 'tmdb'
    void bind(providerName, providerId)
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('detail.rematchDialog.title')}
      description={item?.title}
      width="lg"
      footer={
        <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center">
          <div className="flex flex-1 items-center gap-2">
            <input
              value={manualId}
              onChange={(event) => setManualId(event.target.value)}
              placeholder={t('detail.rematchDialog.manualPlaceholder')}
              className="input py-2.5 text-[13px]"
            />
            <button type="button" onClick={bindManual} className="btn-ghost shrink-0 py-2.5">
              {t('detail.rematchDialog.manualBind')}
            </button>
          </div>
          <button type="button" onClick={onClose} className="btn-ghost">
            {t('common.close')}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="flex rounded-full border border-white/10 bg-white/[0.04] p-1">
            {(['tmdb', 'tvdb'] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setProvider(value)}
                className={`rounded-full px-4 py-1.5 text-xs font-semibold uppercase tracking-wide transition ${
                  provider === value
                    ? 'bg-white text-ink-950'
                    : 'text-ink-300 hover:text-white'
                }`}
              >
                {value}
              </button>
            ))}
          </div>
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('detail.rematchDialog.keyword')}
              className="input pl-10"
              autoFocus
            />
          </div>
        </div>

        {error ? (
          <p className="rounded-xl border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
            {error}
          </p>
        ) : null}

        {candidates.isFetching ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-ink-400">
            <Spinner className="h-4 w-4 text-accent" />
            搜索中…
          </div>
        ) : list.length ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {list.map((candidate) => (
              <button
                key={`${candidate.provider}-${candidate.provider_id}`}
                type="button"
                onClick={() => bind(candidate.provider, candidate.provider_id)}
                disabled={match.isPending}
                className="group flex gap-3 rounded-2xl border border-white/8 bg-white/[0.025] p-2.5 text-left transition hover:border-accent/40 hover:bg-white/[0.05] disabled:opacity-60"
              >
                <ImageWithFallback
                  src={candidate.poster_url}
                  alt={candidate.title}
                  className="h-[96px] w-[64px] shrink-0 rounded-lg"
                />
                <div className="min-w-0 flex-1 py-0.5">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-white/10 px-1.5 py-0.5 text-[9px] font-bold uppercase text-ink-300">
                      {candidate.provider}
                    </span>
                    {candidate.year ? (
                      <span className="text-[11px] text-ink-400">{candidate.year}</span>
                    ) : null}
                    <span className="ml-auto text-[10px] text-accent/80">
                      {(candidate.score * 100).toFixed(0)}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-1 text-[13px] font-semibold text-white">
                    {candidate.title}
                  </p>
                  {candidate.original_title ? (
                    <p className="line-clamp-1 text-[11px] text-ink-400">
                      {candidate.original_title}
                    </p>
                  ) : null}
                  <p className="mt-1 line-clamp-2 text-[10.5px] leading-relaxed text-ink-400">
                    {candidate.overview || '暂无简介'}
                  </p>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <p className="py-10 text-center text-sm text-ink-400">
            {t('detail.rematchDialog.empty')}
          </p>
        )}
      </div>
    </Modal>
  )
}
