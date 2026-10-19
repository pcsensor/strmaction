import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowRight, RefreshCw, Search } from 'lucide-react'
import { useItems } from '../api/hooks'
import { ImageWithFallback } from '../components/ImageWithFallback'
import { EmptyState } from '../components/EmptyState'
import { Spinner } from '../components/Spinner'
import { t } from '../i18n/zh-CN'

export function FixPage() {
  const [tab, setTab] = useState<'failed' | 'pending'>('failed')
  const failed = useItems({ match_state: 'failed', page_size: 100, sort: 'updated' })
  const pending = useItems({ match_state: 'pending', page_size: 100, sort: 'updated' })
  const active = tab === 'failed' ? failed : pending

  const items = useMemo(() => active.data?.items ?? [], [active.data])
  const total = active.data?.total ?? 0

  return (
    <div className="mx-auto max-w-6xl px-5 pb-24 pt-28 sm:px-10">
      <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-accent/80">
        METADATA REVIEW
      </p>
      <h1 className="mt-2 font-display text-3xl font-black tracking-tight text-white">
        待修正条目
      </h1>
      <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-ink-400">
        自动匹配失败或置信度不足的条目会出现在这里。打开详情页点「重新匹配」，即可搜索并绑定正确的 TMDB / TVDB 条目。
      </p>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="flex rounded-full border border-white/10 bg-white/[0.03] p-1">
          {(
            [
              ['failed', `匹配失败 ${failed.data?.total ?? 0}`],
              ['pending', `待确认 ${pending.data?.total ?? 0}`],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setTab(value)}
              className={`rounded-full px-4 py-1.5 text-[12px] font-medium transition ${
                tab === value ? 'bg-white text-ink-950' : 'text-ink-300 hover:text-white'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => active.refetch()}
          className="btn-ghost gap-1.5 px-3.5 py-2 text-[12px]"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${active.isFetching ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      <div className="mt-6">
        {active.isLoading ? (
          <div className="flex justify-center py-20">
            <Spinner className="h-6 w-6 text-accent" />
          </div>
        ) : items.length ? (
          <>
            <p className="mb-3 text-[11.5px] text-ink-500">共 {total} 条</p>
            <div className="grid gap-2.5 md:grid-cols-2">
              {items.map((item) => (
                <Link
                  key={item.id}
                  to={`/item/${item.id}`}
                  className="group flex items-center gap-3.5 rounded-2xl border border-white/8 bg-white/[0.025] p-3 transition hover:border-amber-300/30 hover:bg-white/[0.05]"
                >
                  <ImageWithFallback
                    src={item.poster}
                    alt={item.title}
                    color={item.color}
                    className="h-[84px] w-[56px] shrink-0 rounded-lg"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-1 text-[13.5px] font-medium text-white">
                      {item.title}
                    </p>
                    <p className="mt-0.5 flex items-center gap-2 text-[11px] text-ink-400">
                      {item.year ? <span>{item.year}</span> : null}
                      <span className="rounded border border-white/10 px-1.5 py-0.5 text-[9.5px] uppercase">
                        {item.kind === 'movie' ? '电影' : item.kind === 'series' ? '剧集' : item.kind}
                      </span>
                      <span className="text-amber-300/80">
                        {item.match_state === 'failed' ? '匹配失败' : '待确认'}
                      </span>
                    </p>
                    <p className="mt-1 line-clamp-1 text-[11px] text-ink-500">
                      {item.overview_short || '暂无简介'}
                    </p>
                  </div>
                  <span className="flex shrink-0 items-center gap-1 text-[11px] text-ink-400 transition group-hover:text-white">
                    <Search className="h-3.5 w-3.5" />
                    修正
                    <ArrowRight className="h-3 w-3" />
                  </span>
                </Link>
              ))}
            </div>
          </>
        ) : (
          <EmptyState
            icon={AlertTriangle}
            title={tab === 'failed' ? '没有失败的条目' : '没有待确认的条目'}
            description="所有条目的元数据都已匹配或已手动处理。"
            action={
              <Link to="/" className="btn-primary">
                回到首页
              </Link>
            }
          />
        )}
      </div>
    </div>
  )
}
