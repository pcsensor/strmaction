import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Clock,
  Loader2,
  RefreshCw,
  ScanLine,
  Sparkles,
  XCircle,
} from 'lucide-react'
import { useLibraries, useTasks } from '../api/hooks'
import type { TaskInfo } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { ProgressBar } from '../components/ProgressBar'
import { formatDateTime, formatRelative } from '../utils/format'
import { t } from '../i18n/zh-CN'

const kindIcon = {
  scan: ScanLine,
  scrape: Sparkles,
  refresh: RefreshCw,
  image: RefreshCw,
}

const kindLabel: Record<string, string> = {
  scan: t('tasks.kind.scan'),
  scrape: t('tasks.kind.scrape'),
  refresh: t('tasks.kind.refresh'),
  image: t('tasks.kind.image'),
}

const statusStyle = {
  running: 'border-sky-400/30 bg-sky-400/10 text-sky-200',
  success: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200',
  failed: 'border-rose-400/30 bg-rose-400/10 text-rose-200',
}

function StatChip({ label, value }: { label: string; value: number | undefined }) {
  if (value === undefined || value === null) return null
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-1 text-[11px] text-ink-300">
      <span className="text-ink-500">{label}</span>
      <span className="font-semibold text-ink-100">{value}</span>
    </span>
  )
}

function TaskCard({ task, libraryName }: { task: TaskInfo; libraryName?: string }) {
  const [open, setOpen] = useState(false)
  const Icon = kindIcon[task.kind] || Sparkles
  const stats = task.stats || {}
  const total = Number(stats.total || stats.scrape_total || 0)
  const done = Number(stats.done || stats.scrape_done || 0)
  const ratio = total > 0 ? Math.min(1, done / total) : task.status === 'success' ? 1 : 0
  const failures = Array.isArray(stats.failures) ? stats.failures : []
  const duration =
    task.finished_at && task.started_at
      ? Math.max(
          0,
          Math.round(
            (new Date(task.finished_at).getTime() - new Date(task.started_at).getTime()) / 1000,
          ),
        )
      : null

  return (
    <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-5 transition hover:border-white/14">
      <div className="flex flex-wrap items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/5 text-accent">
          <Icon className="h-[18px] w-[18px]" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[14px] font-semibold text-white">
              {kindLabel[task.kind] || task.kind}
              {libraryName ? <span className="ml-2 font-normal text-ink-400">{libraryName}</span> : null}
            </h3>
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10.5px] font-medium ${statusStyle[task.status]}`}>
              {task.status === 'running' ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : task.status === 'success' ? (
                <CheckCircle2 className="h-3 w-3" />
              ) : (
                <XCircle className="h-3 w-3" />
              )}
              {t(`tasks.status.${task.status}`)}
            </span>
            {task.message ? (
              <span className="text-[11.5px] text-ink-400">{task.message}</span>
            ) : null}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-500">
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {formatDateTime(task.started_at)}
            </span>
            {lastScanHint(task)}
            {duration !== null ? <span>耗时 {duration}s</span> : null}
          </div>
        </div>
        <span className="text-[11px] text-ink-500">#{task.id}</span>
      </div>

      {task.status === 'running' ? (
        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between text-[11px] text-ink-400">
            <span>{t('tasks.progress')}</span>
            <span>
              {done} / {total || '?'}
            </span>
          </div>
          <ProgressBar value={ratio} />
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-1.5">
        <StatChip label={t('tasks.scanned')} value={stats.scanned} />
        <StatChip label={t('tasks.parsed')} value={stats.parsed} />
        <StatChip label={t('tasks.skipped')} value={stats.skipped} />
        <StatChip label={t('tasks.addedItems')} value={stats.added_items} />
        <StatChip label={t('tasks.invalid')} value={stats.invalid} />
        <StatChip label={t('tasks.ok')} value={stats.ok} />
        <StatChip label={t('tasks.failedCount')} value={stats.failed} />
        <StatChip label={t('tasks.skippedCount')} value={stats.skipped_count} />
      </div>

      {failures.length ? (
        <div className="mt-4">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="flex items-center gap-1.5 text-[12px] text-amber-300 transition hover:text-amber-200"
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            {t('tasks.failures')}（{failures.length}）
            <ChevronDown className={`h-3.5 w-3.5 transition ${open ? 'rotate-180' : ''}`} />
          </button>
          {open ? (
            <div className="mt-2.5 max-h-64 space-y-1.5 overflow-y-auto rounded-xl border border-white/8 bg-black/25 p-3">
              {failures.map((failure, index) => (
                <div key={`${failure.item_id}-${index}`} className="flex flex-wrap items-center gap-2 text-[11px]">
                  <span className="rounded bg-white/8 px-1.5 py-0.5 font-mono text-ink-300">
                    #{failure.item_id}
                  </span>
                  <span className="text-rose-300">{failure.reason}</span>
                  {failure.errors?.length ? (
                    <span className="text-ink-500">{failure.errors.join(' / ')}</span>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
          <p className="mt-2 text-[10.5px] text-ink-600">{t('tasks.retryHint')}</p>
        </div>
      ) : null}
    </div>
  )
}

function lastScanHint(task: TaskInfo) {
  if (!task.finished_at) return null
  return <span>{t('tasks.finishedAt', { time: formatRelative(task.finished_at) })}</span>
}

export function TasksPage() {
  const tasks = useTasks()
  const libraries = useLibraries()
  const [filter, setFilter] = useState<'all' | 'running' | 'failed'>('all')

  const libraryNames = useMemo(() => {
    const map = new Map<number, string>()
    libraries.data?.libraries.forEach((library) => map.set(library.id, library.name))
    return map
  }, [libraries.data])

  const list = useMemo(() => {
    const rows = tasks.data?.tasks ?? []
    if (filter === 'running') return rows.filter((task) => task.status === 'running')
    if (filter === 'failed') return rows.filter((task) => task.status === 'failed')
    return rows
  }, [filter, tasks.data])

  const running = (tasks.data?.tasks ?? []).filter((task) => task.status === 'running').length

  return (
    <div className="mx-auto max-w-5xl px-5 pb-24 pt-28 sm:px-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-accent/80">
            ACTIVITY
          </p>
          <h1 className="mt-2 font-display text-3xl font-black tracking-tight text-white">
            {t('tasks.title')}
          </h1>
          <p className="mt-2 text-[13px] text-ink-400">{t('tasks.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          {running > 0 ? (
            <span className="flex items-center gap-1.5 rounded-full border border-sky-400/25 bg-sky-400/10 px-3 py-1.5 text-[11.5px] text-sky-200">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {running} 个运行中
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => tasks.refetch()}
            className="btn-ghost gap-1.5 py-2"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${tasks.isFetching ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </div>
      </div>

      <div className="mt-6 flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] p-1 sm:w-fit">
        {(
          [
            ['all', '全部'],
            ['running', '运行中'],
            ['failed', '失败'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            className={`rounded-full px-4 py-1.5 text-[12px] font-medium transition ${
              filter === value ? 'bg-white text-ink-950' : 'text-ink-300 hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-6 space-y-3">
        {tasks.isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, index) => (
              <div key={index} className="skeleton h-32 rounded-2xl" />
            ))}
          </div>
        ) : list.length ? (
          list.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              libraryName={
                task.library_id ? libraryNames.get(task.library_id) || `库 #${task.library_id}` : undefined
              }
            />
          ))
        ) : (
          <EmptyState
            icon={ScanLine}
            title={t('tasks.empty')}
            description={t('tasks.emptyHint')}
            action={
              <a href="/settings" className="btn-primary">
                去设置
              </a>
            }
          />
        )}
      </div>

      {running > 0 ? (
        <p className="mt-6 text-center text-[11px] text-ink-500">{t('tasks.runningHint')}</p>
      ) : null}
    </div>
  )
}
