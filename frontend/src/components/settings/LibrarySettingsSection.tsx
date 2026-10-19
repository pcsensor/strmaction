import { useEffect, useRef, useState } from 'react'
import {
  Film,
  FolderPlus,
  Library,
  Loader2,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  ScanLine,
  Sparkles,
  Trash2,
  Tv,
  Wand2,
} from 'lucide-react'
import type { LibraryInfo, LibraryType } from '../../api/types'
import {
  useCreateLibrary,
  useDeleteLibrary,
  useLibraryTask,
  useTasks,
  useUpdateLibrary,
} from '../../api/hooks'
import { Modal } from '../Modal'
import { EmptyState } from '../EmptyState'
import { useToast } from '../../store/ui'
import { formatRelative } from '../../utils/format'
import { t } from '../../i18n/zh-CN'
import { Section, Field, headersToText, textToHeaders } from './common'

const typeIcon: Record<LibraryType, typeof Film> = {
  movie: Film,
  tv: Tv,
  home: Play,
  course: Sparkles,
}

const typeOrder: LibraryType[] = ['movie', 'tv', 'home', 'course']

interface LibraryFormState {
  name: string
  root_path: string
  type: LibraryType
  scan_cron: string
  template: string
  tvdb_season_type: string
  auto_scrape: boolean
  enabled: boolean
  priority: string[]
  play_headers: string
}

const emptyLibraryForm: LibraryFormState = {
  name: '',
  root_path: '',
  type: 'movie',
  scan_cron: '',
  template: '',
  tvdb_season_type: '',
  auto_scrape: true,
  enabled: true,
  priority: [],
  play_headers: '',
}

function LibraryCard({
  library,
  onEdit,
  onDeleted,
}: {
  library: LibraryInfo
  onEdit: (library: LibraryInfo) => void
  onDeleted: (id: number) => void
}) {
  const task = useLibraryTask()
  const remove = useDeleteLibrary()
  const toast = useToast()
  const Icon = typeIcon[library.type]
  const counts = library.counts || {}
  const [busy, setBusy] = useState<string | null>(null)

  const run = async (action: 'scan' | 'scrape' | 'refresh') => {
    setBusy(action)
    try {
      await task.mutateAsync({ id: library.id, action })
      toast({
        title:
          action === 'scan'
            ? t('library.scanStarted')
            : action === 'scrape'
              ? t('library.scrapeStarted')
              : t('library.refreshStarted'),
        tone: 'success',
      })
    } catch (error) {
      toast({ title: t('common.failed'), description: (error as Error).message, tone: 'error' })
    } finally {
      setBusy(null)
    }
  }

  const onDelete = async () => {
    if (!window.confirm(t('library.deleteConfirm', { name: library.name }))) return
    try {
      await remove.mutateAsync(library.id)
      toast({ title: t('toast.deleted'), tone: 'success' })
      onDeleted(library.id)
    } catch (error) {
      toast({ title: t('library.errors.deleteFailed'), description: (error as Error).message, tone: 'error' })
    }
  }

  return (
    <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-5">
      <div className="flex flex-wrap items-start gap-3.5">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-white/10 bg-gradient-to-br from-white/10 to-white/[0.02] text-accent">
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[15px] font-semibold text-white">{library.name}</h3>
            {library.name !== t(`library.type.${library.type}`) ? (
              <span className="chip">{t(`library.type.${library.type}`)}</span>
            ) : null}
            {!library.enabled ? (
              <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-ink-400">
                已禁用
              </span>
            ) : null}
            {library.provider_priority?.length ? (
              <span className="text-[10.5px] uppercase tracking-wide text-accent/70">
                {library.provider_priority.join(' → ')}
              </span>
            ) : null}
          </div>
          <p className="mt-1 break-all font-mono text-[11.5px] text-ink-400">{library.root_path}</p>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-500">
            {library.type === 'movie' ? (
              <span>{counts.movie ?? counts.movies ?? 0} 部电影</span>
            ) : null}
            {library.type === 'tv' ? (
              <>
                <span>{counts.series ?? 0} 部剧集</span>
                <span>{counts.episode ?? counts.episodes ?? 0} 集</span>
              </>
            ) : null}
            {library.type === 'home' ? (
              <>
                <span>{counts.series ?? 0} 个分组</span>
                <span>{counts.video ?? 0} 个视频</span>
              </>
            ) : null}
            {library.type === 'course' ? (
              <>
                <span>{counts.series ?? 0} 门课程</span>
                <span>{counts.episode ?? 0} 个章节</span>
              </>
            ) : null}
            <span>{counts.files ?? 0} 个文件</span>
            <span>
              {library.last_scan_at
                ? t('library.lastScan', { time: formatRelative(library.last_scan_at) })
                : t('library.neverScanned')}
            </span>
            {library.scan_cron ? <span className="font-mono">{library.scan_cron}</span> : null}
            {Object.keys(library.play_headers || {}).length ? (
              <span className="chip px-2 py-0.5 text-[10px]">
                {Object.keys(library.play_headers).length} 个播放请求头
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => run('scan')}
            disabled={busy !== null}
            className="btn-ghost gap-1.5 px-3.5 py-2 text-[12px]"
          >
            {busy === 'scan' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ScanLine className="h-3.5 w-3.5" />}
            {t('library.scanNow')}
          </button>
          <button
            type="button"
            onClick={() => run('scrape')}
            disabled={busy !== null}
            className="btn-ghost gap-1.5 px-3.5 py-2 text-[12px]"
          >
            {busy === 'scrape' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
            {t('library.scrapeNow')}
          </button>
          <button
            type="button"
            onClick={() => run('refresh')}
            disabled={busy !== null}
            className="btn-icon"
            title={t('library.refreshAll')}
          >
            {busy === 'refresh' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          </button>
          <button type="button" onClick={() => onEdit(library)} className="btn-icon" title={t('common.edit')}>
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button type="button" onClick={onDelete} className="btn-icon hover:!border-rose-400/40 hover:!text-rose-300" title={t('common.delete')}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}

export function LibrarySettingsSection({
  libraries,
  onRefresh,
}: {
  libraries: LibraryInfo[]
  onRefresh: () => void
}) {
  const createLibrary = useCreateLibrary()
  const updateLibrary = useUpdateLibrary()
  const toast = useToast()
  const tasksQuery = useTasks()
  const prevRunningRef = useRef(false)
  const isRunning = tasksQuery.data?.tasks?.some(
    (task) => task.status === 'running' && task.library_id != null
  ) ?? false

  useEffect(() => {
    if (prevRunningRef.current && !isRunning) {
      onRefresh()
    }
    prevRunningRef.current = isRunning
  }, [isRunning, onRefresh])

  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<LibraryInfo | null>(null)
  const [form, setForm] = useState<LibraryFormState>(emptyLibraryForm)
  const [formError, setFormError] = useState<string | null>(null)

  const openCreate = () => {
    setEditing(null)
    setForm(emptyLibraryForm)
    setFormError(null)
    setModalOpen(true)
  }

  const openEdit = (library: LibraryInfo) => {
    setEditing(library)
    setForm({
      name: library.name,
      root_path: library.root_path,
      type: library.type,
      scan_cron: library.scan_cron || '',
      template: library.template || '',
      tvdb_season_type: library.tvdb_season_type || '',
      auto_scrape: library.auto_scrape,
      enabled: library.enabled,
      priority: library.provider_priority || [],
      play_headers: headersToText(library.play_headers),
    })
    setFormError(null)
    setModalOpen(true)
  }

  const submitLibrary = async () => {
    if (!form.name.trim()) {
      setFormError(t('library.errors.nameRequired'))
      return
    }
    if (!form.root_path.trim().startsWith('/')) {
      setFormError(t('library.errors.rootRequired'))
      return
    }
    const body: Record<string, unknown> = {
      name: form.name.trim(),
      root_path: form.root_path.trim(),
      type: form.type,
      scan_cron: form.scan_cron.trim() || null,
      template: form.template.trim() || null,
      tvdb_season_type: form.tvdb_season_type || null,
      auto_scrape: form.auto_scrape,
      enabled: form.enabled,
      provider_priority: form.priority.length ? form.priority : null,
      play_headers: textToHeaders(form.play_headers),
    }
    try {
      if (editing) {
        await updateLibrary.mutateAsync({ id: editing.id, body })
        toast({ title: t('toast.saved'), tone: 'success' })
      } else {
        await createLibrary.mutateAsync(body)
        toast({ title: t('toast.saved'), tone: 'success' })
      }
      setModalOpen(false)
      onRefresh()
    } catch (error) {
      setFormError((error as Error).message || t('library.errors.createFailed'))
    }
  }

  return (
    <>
      <Section id="libraries" title={t('settings.sections.libraries')} icon={Library}>
        <div className="flex items-center justify-between">
          <p className="text-[12px] text-ink-400">
            扫描 .strm 目录；一个目录对应一个媒体库。
          </p>
          <button type="button" onClick={openCreate} className="btn-primary gap-1.5 px-4 py-2.5 text-[13px]">
            <FolderPlus className="h-4 w-4" />
            {t('library.add')}
          </button>
        </div>
        {libraries.length ? (
          <div className="space-y-3">
            {libraries.map((library) => (
              <LibraryCard
                key={library.id}
                library={library}
                onEdit={openEdit}
                onDeleted={onRefresh}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Library}
            title="还没有媒体库"
            description="添加一个挂载进容器的 .strm 目录，选择类型后开始扫描。"
            action={
              <button type="button" onClick={openCreate} className="btn-primary gap-2">
                <Plus className="h-4 w-4" />
                {t('library.add')}
              </button>
            }
          />
        )}
      </Section>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? t('library.edit') : t('library.add')}
        footer={
          <div className="flex items-center justify-end gap-2">
            <button type="button" onClick={() => setModalOpen(false)} className="btn-ghost">
              {t('common.cancel')}
            </button>
            <button
              type="button"
              onClick={submitLibrary}
              disabled={createLibrary.isPending || updateLibrary.isPending}
              className="btn-primary"
            >
              {createLibrary.isPending || updateLibrary.isPending ? t('common.loading') : t('common.save')}
            </button>
          </div>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Field label={t('library.fields.name')}>
              <input
                className="input"
                value={form.name}
                onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                placeholder={t('library.fields.namePlaceholder')}
              />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label={t('library.fields.rootPath')} hint={t('library.fields.rootPathHint')}>
              <input
                className="input font-mono text-[13px]"
                value={form.root_path}
                onChange={(event) => setForm((prev) => ({ ...prev, root_path: event.target.value }))}
                placeholder="/media/movies"
              />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label={t('library.fields.type')}>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {typeOrder.map((type) => {
                  const Icon = typeIcon[type]
                  const active = form.type === type
                  return (
                    <button
                      key={type}
                      type="button"
                      onClick={() => setForm((prev) => ({ ...prev, type }))}
                      className={`flex flex-col items-center gap-1.5 rounded-xl border p-3 text-center transition ${
                        active
                          ? 'border-accent/60 bg-accent/15 text-accent shadow-[0_0_16px_rgba(232,176,106,0.15)]'
                          : 'border-white/10 bg-white/[0.03] text-ink-300 hover:border-white/20'
                      }`}
                    >
                      <Icon className="h-5 w-5" />
                      <span className="text-[12px] font-medium">{t(`library.type.${type}`)}</span>
                    </button>
                  )
                })}
              </div>
            </Field>
          </div>
          <Field label={t('library.fields.scanCron')} hint={t('library.fields.scanCronPlaceholder')}>
            <input
              className="input font-mono text-[13px]"
              value={form.scan_cron}
              onChange={(event) => setForm((prev) => ({ ...prev, scan_cron: event.target.value }))}
              placeholder="0 3 * * *"
            />
          </Field>
          <Field label={t('library.fields.seasonType')}>
            <select
              className="input"
              value={form.tvdb_season_type}
              onChange={(event) => setForm((prev) => ({ ...prev, tvdb_season_type: event.target.value }))}
            >
              <option value="">跟随全局</option>
              <option value="default">{t('library.fields.seasonTypeDefault')}</option>
              <option value="absolute">{t('library.fields.seasonTypeAbsolute')}</option>
              <option value="dvd">{t('library.fields.seasonTypeDvd')}</option>
            </select>
          </Field>
          <div className="sm:col-span-2">
            <Field label={t('library.fields.template')} hint={t('library.fields.templateHint')}>
              <input
                className="input font-mono text-[12.5px]"
                value={form.template}
                onChange={(event) => setForm((prev) => ({ ...prev, template: event.target.value }))}
                placeholder={t('library.fields.templatePlaceholder')}
              />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label={t('library.fields.priority')} hint={t('library.fields.priorityHint')}>
              <div className="flex flex-wrap gap-2">
                {['tmdb', 'tvdb'].map((provider) => {
                  const active = form.priority.includes(provider)
                  return (
                    <button
                      key={provider}
                      type="button"
                      onClick={() =>
                        setForm((prev) => ({
                          ...prev,
                          priority: active
                            ? prev.priority.filter((item) => item !== provider)
                            : [...prev.priority, provider],
                        }))
                      }
                      className={`rounded-full border px-4 py-2 text-[12px] uppercase transition ${
                        active
                          ? 'border-accent/60 bg-accent/15 text-accent'
                          : 'border-white/10 bg-white/[0.03] text-ink-300'
                      }`}
                    >
                      {provider}
                    </button>
                  )
                })}
                {form.priority.length ? (
                  <span className="self-center text-[11px] text-ink-500">
                    {form.priority.join(' → ')}
                  </span>
                ) : null}
              </div>
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label={t('library.fields.playHeaders')} hint={t('library.fields.playHeadersHint')}>
              <textarea
                className="input min-h-[80px] font-mono text-[12px] leading-relaxed"
                value={form.play_headers}
                onChange={(event) => setForm((prev) => ({ ...prev, play_headers: event.target.value }))}
                placeholder={t('library.fields.playHeadersPlaceholder')}
              />
            </Field>
          </div>
          <label className="flex items-center gap-2.5 text-[12.5px] text-ink-200">
            <input
              type="checkbox"
              checked={form.auto_scrape}
              onChange={(event) => setForm((prev) => ({ ...prev, auto_scrape: event.target.checked }))}
              className="h-4 w-4 accent-[#e8b06a]"
            />
            {t('library.fields.autoScrape')}
          </label>
          <label className="flex items-center gap-2.5 text-[12.5px] text-ink-200">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) => setForm((prev) => ({ ...prev, enabled: event.target.checked }))}
              className="h-4 w-4 accent-[#e8b06a]"
            />
            {t('library.fields.enabled')}
          </label>
        </div>
        {formError ? (
          <p className="mt-4 rounded-xl border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
            {formError}
          </p>
        ) : null}
      </Modal>
    </>
  )
}
