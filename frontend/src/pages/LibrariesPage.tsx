import { useState, useMemo, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Film,
  Folder,
  Home as HomeIcon,
  Library as LibraryIcon,
  Play,
  Tv,
  Video,
} from 'lucide-react'
import { useLibraries, useItems } from '../api/hooks'
import type { ItemSummary, LibraryInfo } from '../api/types'
import { PosterCard } from '../components/PosterCard'
import { EpisodeCard } from '../components/EpisodeCard'
import { EmptyState } from '../components/EmptyState'
import { PosterSkeleton } from '../components/Skeleton'
import { LoadingBlock } from '../components/Spinner'
import { t } from '../i18n/zh-CN'

function libIcon(type: string) {
  switch (type) {
    case 'movie':
      return <Film className="h-5 w-5 text-accent" />
    case 'tv':
      return <Tv className="h-5 w-5 text-sky-400" />
    case 'course':
      return <BookOpen className="h-5 w-5 text-emerald-400" />
    case 'home':
      return <HomeIcon className="h-5 w-5 text-rose-400" />
    default:
      return <Video className="h-5 w-5 text-amber-400" />
  }
}

function libTypeLabel(type: string) {
  switch (type) {
    case 'movie':
      return '电影'
    case 'tv':
      return '电视剧'
    case 'course':
      return '课程'
    case 'home':
      return '家庭视频'
    default:
      return type
  }
}

function libCountSummary(lib: LibraryInfo) {
  const counts = lib.counts || {}
  const parts: string[] = []
  if (counts.movie) parts.push(`${counts.movie} 部电影`)
  if (counts.series) parts.push(`${counts.series} 部剧集`)
  if (counts.folder) parts.push(`${counts.folder} 个目录`)
  if (counts.video) parts.push(`${counts.video} 个视频`)
  if (parts.length === 0 && counts.files) parts.push(`${counts.files} 个文件`)
  return parts.join(' · ') || '已就绪'
}

export function LibrariesPage() {
  const [params, setParams] = useSearchParams()
  const { data: libData, isLoading: libLoading } = useLibraries()
  const libraries = libData?.libraries || []

  const activeLibId = useMemo(() => {
    const rawId = Number(params.get('id'))
    if (rawId && libraries.some((l) => l.id === rawId)) {
      return rawId
    }
    return libraries[0]?.id ?? null
  }, [params, libraries])

  const [sort, setSort] = useState('recent')
  const [page, setPage] = useState(1)

  // 当切换库时重置页码
  useEffect(() => {
    setPage(1)
  }, [activeLibId])

  const activeLib = useMemo(
    () => libraries.find((l) => l.id === activeLibId) || null,
    [libraries, activeLibId],
  )

  const isTreeType = activeLib?.type === 'course' || activeLib?.type === 'home'

  // 影视库查询
  const itemsQuery = useItems({
    library_id: activeLibId || undefined,
    parent_id: isTreeType ? 'root' : undefined,
    sort: isTreeType ? undefined : sort,
    page: isTreeType ? 1 : page,
    page_size: isTreeType ? 100 : 48,
  })

  const selectLibrary = (id: number) => {
    const next = new URLSearchParams(params)
    next.set('id', String(id))
    setParams(next)
  }

  if (libLoading) {
    return (
      <div className="mx-auto max-w-[1680px] px-5 pb-24 pt-28 sm:px-10 lg:px-16">
        <LoadingBlock />
      </div>
    )
  }

  if (!libraries.length) {
    return (
      <div className="mx-auto max-w-2xl px-5 pt-32">
        <EmptyState
          icon={LibraryIcon}
          title="暂无可访问的媒体库"
          description="当前账号尚未被授权访问任何媒体库，请联系系统管理员分配权限。"
          action={
            <Link to="/" className="btn-primary">
              返回首页
            </Link>
          }
        />
      </div>
    )
  }

  const items = itemsQuery.data?.items || []
  const total = itemsQuery.data?.total || 0
  const totalPages = itemsQuery.data?.pages || 1

  const folders = items.filter((i) => i.kind === 'folder')
  const directVideos = items.filter((i) => i.kind === 'video')

  return (
    <div className="mx-auto max-w-[1680px] px-5 pb-24 pt-28 sm:px-10 lg:px-16">
      {/* 页面标题 */}
      <div className="mb-8">
        <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-accent/80">
          LIBRARIES
        </p>
        <h1 className="mt-2 font-display text-3xl font-black tracking-tight text-white sm:text-4xl">
          媒体库
        </h1>
        <p className="mt-2 text-sm text-ink-300">
          浏览您有权限访问的全部媒体库与收录资源
        </p>
      </div>

      {/* 媒体库横向卡片切换栏 */}
      <div className="no-scrollbar mb-10 flex gap-3 overflow-x-auto pb-2">
        {libraries.map((lib) => {
          const active = lib.id === activeLibId
          return (
            <button
              key={lib.id}
              type="button"
              onClick={() => selectLibrary(lib.id)}
              className={`group flex shrink-0 items-center gap-3.5 rounded-2xl border px-4 py-3 text-left transition duration-300 focus-ring ${
                active
                  ? 'border-accent/50 bg-accent/[0.08] shadow-lift'
                  : 'border-white/8 bg-white/[0.025] hover:border-white/20 hover:bg-white/[0.05]'
              }`}
            >
              <div
                className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl transition duration-300 ${
                  active
                    ? 'bg-accent/20 text-accent'
                    : 'bg-white/5 text-ink-300 group-hover:bg-white/10 group-hover:text-white'
                }`}
              >
                {libIcon(lib.type)}
              </div>
              <div className="min-w-0 pr-2">
                <div className="flex items-center gap-2">
                  <h3
                    className={`line-clamp-1 text-sm font-semibold transition ${
                      active ? 'text-white' : 'text-ink-200 group-hover:text-white'
                    }`}
                  >
                    {lib.name}
                  </h3>
                  <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-medium text-ink-300">
                    {libTypeLabel(lib.type)}
                  </span>
                </div>
                <p className="mt-1 text-[11.5px] text-ink-400">
                  {libCountSummary(lib)}
                </p>
              </div>
            </button>
          )
        })}
      </div>

      {/* 媒体库内容区 */}
      {activeLib ? (
        <div>
          {/* 工具栏：标题与排序 */}
          <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-white/8 pb-4">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-bold text-white">
                {activeLib.name}
              </h2>
              <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-xs text-ink-300">
                {isTreeType ? `${folders.length} 个文件夹 · ${directVideos.length} 部视频` : `${total} 部作品`}
              </span>
            </div>

            {!isTreeType && total > 0 ? (
              <div className="flex items-center gap-2 text-xs">
                <span className="text-ink-400">排序：</span>
                <select
                  value={sort}
                  onChange={(e) => {
                    setSort(e.target.value)
                    setPage(1)
                  }}
                  className="rounded-xl border border-white/10 bg-[#0e1219] px-3 py-1.5 text-ink-200 transition focus:border-accent focus:outline-none"
                >
                  <option value="recent">最新入库</option>
                  <option value="rating">评分最高</option>
                  <option value="year">上映年份</option>
                  <option value="title">名称排序</option>
                </select>
              </div>
            ) : null}
          </div>

          {/* 渲染内容 */}
          {itemsQuery.isLoading ? (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
              {Array.from({ length: 12 }).map((_, i) => (
                <PosterSkeleton key={i} />
              ))}
            </div>
          ) : isTreeType ? (
            /* 课程与家庭视频：树型目录展示 */
            <div className="space-y-10">
              {folders.length > 0 ? (
                <section>
                  <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-ink-300">
                    <Folder className="h-4 w-4 text-amber-400" />
                    目录树 ({folders.length})
                  </h3>
                  <div className="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {folders.map((folder) => (
                      <Link
                        key={folder.id}
                        to={`/item/${folder.id}`}
                        data-focusable
                        className="group flex items-center gap-4 rounded-2xl border border-white/8 bg-white/[0.025] p-4 transition duration-300 hover:border-amber-400/40 hover:bg-amber-400/[0.06] focus-ring"
                      >
                        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-amber-400/10 text-amber-300 transition group-hover:scale-105 group-hover:bg-amber-400/20">
                          <Folder className="h-6 w-6" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <h4 className="line-clamp-1 text-[14.5px] font-medium text-ink-100 transition group-hover:text-white">
                            {folder.title}
                          </h4>
                          <p className="mt-0.5 text-[11.5px] text-ink-400">
                            点击进入浏览子目录与课程
                          </p>
                        </div>
                        <ChevronRight className="h-4 w-4 shrink-0 text-ink-500 transition group-hover:translate-x-0.5 group-hover:text-amber-300" />
                      </Link>
                    ))}
                  </div>
                </section>
              ) : null}

              {directVideos.length > 0 ? (
                <section>
                  <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-ink-300">
                    <Play className="h-4 w-4 text-accent" />
                    根目录视频 ({directVideos.length})
                  </h3>
                  <div className="grid gap-3 lg:grid-cols-2">
                    {directVideos.map((video) => (
                      <EpisodeCard
                        key={video.id}
                        episode={video as any}
                        active={false}
                        color="#e8b06a"
                      />
                    ))}
                  </div>
                </section>
              ) : null}

              {folders.length === 0 && directVideos.length === 0 ? (
                <EmptyState
                  icon={Folder}
                  title="该媒体库尚无视频或目录"
                  description="请确认目录文件是否已生成且格式正确，或在设置中执行扫描。"
                />
              ) : null}
            </div>
          ) : (
            /* 电影与电视剧：海报流展示 */
            <div>
              {items.length > 0 ? (
                <>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
                    {items.map((item) => (
                      <PosterCard
                        key={item.id}
                        item={item}
                        width="w-full"
                        className="!w-full"
                      />
                    ))}
                  </div>

                  {/* 分页控制 */}
                  {totalPages > 1 ? (
                    <div className="mt-12 flex items-center justify-center gap-3">
                      <button
                        type="button"
                        disabled={page <= 1}
                        onClick={() => {
                          setPage((p) => Math.max(1, p - 1))
                          window.scrollTo({ top: 0, behavior: 'smooth' })
                        }}
                        className="btn-ghost gap-1.5 px-4 py-2 text-xs disabled:opacity-30"
                      >
                        <ChevronLeft className="h-4 w-4" />
                        上一页
                      </button>
                      <span className="text-xs text-ink-400">
                        第 {page} / {totalPages} 页
                      </span>
                      <button
                        type="button"
                        disabled={page >= totalPages}
                        onClick={() => {
                          setPage((p) => Math.min(totalPages, p + 1))
                          window.scrollTo({ top: 0, behavior: 'smooth' })
                        }}
                        className="btn-ghost gap-1.5 px-4 py-2 text-xs disabled:opacity-30"
                      >
                        下一页
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                  ) : null}
                </>
              ) : (
                <EmptyState
                  icon={Film}
                  title="该媒体库尚无影视作品"
                  description="可能扫描尚未完成，或目录内暂无有效影视文件。"
                />
              )}
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
