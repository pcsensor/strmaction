import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  CheckCircle2,
  Database,
  Download,
  Film,
  FolderPlus,
  KeyRound,
  Library,
  Loader2,
  Lock,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Trash2,
  Tv,
  Upload,
  Wand2,
  X,
} from 'lucide-react'
import type { AppSettings, LibraryInfo, LibraryType } from '../api/types'
import {
  useCreateLibrary,
  useDeleteLibrary,
  useExportData,
  useImportData,
  useLibraries,
  useLibraryTask,
  usePatchSettings,
  useProviderTest,
  useSettings,
  useChangePassword,
  useUpdateLibrary,
} from '../api/hooks'
import { Modal } from '../components/Modal'
import { Spinner } from '../components/Spinner'
import { EmptyState } from '../components/EmptyState'
import { useToast } from '../store/ui'
import { formatRelative } from '../utils/format'
import { cnDate } from '../utils/format'
import { t } from '../i18n/zh-CN'

const typeIcon: Record<LibraryType, typeof Film> = {
  movie: Film,
  tv: Tv,
  home: Play,
  course: Sparkles,
}

const typeOrder: LibraryType[] = ['movie', 'tv', 'home', 'course']

function Section({
  id,
  title,
  description,
  icon: Icon,
  children,
}: {
  id: string
  title: string
  description?: string
  icon: typeof Film
  children: React.ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-28">
      <div className="mb-4 flex items-start gap-3">
        <div className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/5 text-accent">
          <Icon className="h-[17px] w-[17px]" />
        </div>
        <div>
          <h2 className="font-display text-lg font-semibold text-white">{title}</h2>
          {description ? <p className="mt-0.5 text-[12.5px] text-ink-400">{description}</p> : null}
        </div>
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint ? <p className="mt-1.5 text-[11px] leading-relaxed text-ink-500">{hint}</p> : null}
    </div>
  )
}

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

function headersToText(headers?: Record<string, string> | null): string {
  if (!headers) return ''
  return Object.entries(headers)
    .map(([key, value]) => `${key}: ${value}`)
    .join('\n')
}

function textToHeaders(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const index = line.indexOf(':')
    if (index <= 0) continue
    const key = line.slice(0, index).trim()
    const value = line.slice(index + 1).trim()
    if (!key || !value) continue
    out[key] = value
  }
  return out
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

export function SettingsPage() {
  const settingsQuery = useSettings()
  const librariesQuery = useLibraries()
  const patchSettings = usePatchSettings()
  const providerTest = useProviderTest()
  const changePassword = useChangePassword()
  const createLibrary = useCreateLibrary()
  const updateLibrary = useUpdateLibrary()
  const exportData = useExportData()
  const importData = useImportData()
  const toast = useToast()

  const [tmdbKey, setTmdbKey] = useState('')
  const [tmdbBase, setTmdbBase] = useState('')
  const [tmdbProxy, setTmdbProxy] = useState('')
  const [tvdbKey, setTvdbKey] = useState('')
  const [tvdbPin, setTvdbPin] = useState('')
  const [tvdbBase, setTvdbBase] = useState('')
  const [tvdbProxy, setTvdbProxy] = useState('')
  const [language, setLanguage] = useState('zh-CN')
  const [seasonType, setSeasonType] = useState('default')
  const [priority, setPriority] = useState<Record<string, string[]>>({
    movie: ['tmdb', 'tvdb'],
    tv: ['tmdb', 'tvdb'],
    home: [],
    course: [],
  })
  const [threshold, setThreshold] = useState('0.75')
  const [refreshDays, setRefreshDays] = useState('30')
  const [playerMode, setPlayerMode] = useState<string>('builtin')
  const [progressInterval, setProgressInterval] = useState('5000')
  const [tokenTtl, setTokenTtl] = useState('12')
  const [fallbackOnError, setFallbackOnError] = useState(true)
  const [playHeadersGlobal, setPlayHeadersGlobal] = useState('')
  const [mpvPath, setMpvPath] = useState('')
  const [mpvArgs, setMpvArgs] = useState('')
  const [enableProgress, setEnableProgress] = useState(true)
  const [ignore, setIgnore] = useState('')
  const [followSymlinks, setFollowSymlinks] = useState(false)
  const [maxDepth, setMaxDepth] = useState('6')
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; message: string; latency: number }>>({})
  const [libraryModal, setLibraryModal] = useState(false)
  const [editing, setEditing] = useState<LibraryInfo | null>(null)
  const [libraryForm, setLibraryForm] = useState<LibraryFormState>(emptyLibraryForm)
  const [formError, setFormError] = useState<string | null>(null)
  const [passwordForm, setPasswordForm] = useState({ current: '', next: '', confirm: '' })
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)

  const settings = settingsQuery.data?.settings
  const companion = typeof window !== 'undefined' ? window.StrmActionNative : undefined

  useEffect(() => {
    if (!settings) return
    setTmdbKey(settings.scraper.tmdb.api_key || '')
    setTmdbBase(settings.scraper.tmdb.base_url || '')
    setTmdbProxy(settings.scraper.tmdb.proxy || '')
    setTvdbKey(settings.scraper.tvdb.api_key || '')
    setTvdbPin(settings.scraper.tvdb.pin || '')
    setTvdbBase(settings.scraper.tvdb.base_url || '')
    setTvdbProxy(settings.scraper.tvdb.proxy || '')
    setLanguage(settings.scraper.language || 'zh-CN')
    setSeasonType(settings.scraper.tvdb.season_type || 'default')
    setPriority({
      movie: settings.scraper.provider_priority.movie || [],
      tv: settings.scraper.provider_priority.tv || [],
      home: settings.scraper.provider_priority.home || [],
      course: settings.scraper.provider_priority.course || [],
    })
    setThreshold(String(settings.scraper.match_threshold ?? 0.75))
    setRefreshDays(String(settings.scraper.auto_refresh_days ?? 30))
    setPlayerMode(settings.player.mode || 'builtin')
    setProgressInterval(String(settings.player.progress_interval_ms ?? 5000))
    setTokenTtl(String(settings.player.play_token_ttl_hours ?? 12))
    setFallbackOnError(settings.player.fallback_on_error !== false)
    setPlayHeadersGlobal(headersToText(settings.player.play_headers))
    setMpvPath(settings.player.mpv_path || '')
    setMpvArgs((settings.player.mpv_extra_args || []).join('\n'))
    setEnableProgress(Boolean(settings.player.enable_progress))
    setIgnore((settings.scanner.ignore || []).join('\n'))
    setFollowSymlinks(Boolean(settings.scanner.follow_symlinks))
    setMaxDepth(String(settings.scanner.max_depth ?? 6))
  }, [settings])

  const libraries = librariesQuery.data?.libraries ?? []
  const providers = useMemo(
    () => [
      { key: 'tmdb', label: 'TMDB', hint: t('settings.providers.tmdbHint') },
      { key: 'tvdb', label: 'TVDB', hint: t('settings.providers.tvdbHint') },
    ],
    [],
  )

  const save = async (patch: Record<string, unknown>, successTitle = t('settings.saved')) => {
    try {
      await patchSettings.mutateAsync(patch)
      toast({ title: successTitle, tone: 'success' })
      return true
    } catch (error) {
      toast({ title: t('settings.saveFailed'), description: (error as Error).message, tone: 'error' })
      return false
    }
  }

  const saveTmdb = () =>
    save({
      scraper: {
        tmdb: {
          api_key: tmdbKey,
          base_url: tmdbBase || undefined,
          proxy: tmdbProxy,
        },
      },
    })

  const saveTvdb = () =>
    save({
      scraper: {
        tvdb: {
          api_key: tvdbKey,
          pin: tvdbPin,
          base_url: tvdbBase || undefined,
          proxy: tvdbProxy,
        },
      },
    })

  const runTest = async (provider: 'tmdb' | 'tvdb') => {
    try {
      const result = await providerTest.mutateAsync(provider)
      setTestResult((prev) => ({
        ...prev,
        [provider]: { ok: result.ok, message: result.message, latency: result.latency_ms },
      }))
    } catch (error) {
      setTestResult((prev) => ({
        ...prev,
        [provider]: { ok: false, message: (error as Error).message, latency: 0 },
      }))
    }
  }

  const openCreate = () => {
    setEditing(null)
    setLibraryForm(emptyLibraryForm)
    setFormError(null)
    setLibraryModal(true)
  }

  const openEdit = (library: LibraryInfo) => {
    setEditing(library)
    setLibraryForm({
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
    setLibraryModal(true)
  }

  const submitLibrary = async () => {
    if (!libraryForm.name.trim()) {
      setFormError(t('library.errors.nameRequired'))
      return
    }
    if (!libraryForm.root_path.trim().startsWith('/')) {
      setFormError(t('library.errors.rootRequired'))
      return
    }
    const body: Record<string, unknown> = {
      name: libraryForm.name.trim(),
      root_path: libraryForm.root_path.trim(),
      type: libraryForm.type,
      scan_cron: libraryForm.scan_cron.trim() || null,
      template: libraryForm.template.trim() || null,
      tvdb_season_type: libraryForm.tvdb_season_type || null,
      auto_scrape: libraryForm.auto_scrape,
      enabled: libraryForm.enabled,
      provider_priority: libraryForm.priority.length ? libraryForm.priority : null,
      play_headers: textToHeaders(libraryForm.play_headers),
    }
    try {
      if (editing) {
        await updateLibrary.mutateAsync({ id: editing.id, body })
        toast({ title: t('toast.saved'), tone: 'success' })
      } else {
        await createLibrary.mutateAsync(body)
        toast({ title: t('toast.saved'), tone: 'success' })
      }
      setLibraryModal(false)
    } catch (error) {
      setFormError((error as Error).message || t('library.errors.createFailed'))
    }
  }

  const doExport = async () => {
    try {
      const data = await exportData.mutateAsync()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = t('settings.data.backupName', { date: cnDate() })
      anchor.click()
      URL.revokeObjectURL(url)
      toast({ title: '备份已导出', tone: 'success' })
    } catch (error) {
      toast({ title: t('common.failed'), description: (error as Error).message, tone: 'error' })
    }
  }

  const doImport = async (file: File | undefined) => {
    if (!file) return
    try {
      const text = await file.text()
      const data = JSON.parse(text) as Record<string, unknown>
      const result = await importData.mutateAsync(data)
      const imported = result.imported || {}
      toast({
        title: t('settings.data.imported', {
          libraries: Number(imported.libraries || 0),
          items: Number(imported.items || 0),
          progress: Number(imported.progress || 0),
        }),
        description: '建议重新扫描目录以恢复文件关联',
        tone: 'success',
        timeout: 7000,
      })
    } catch (error) {
      toast({ title: '导入失败', description: (error as Error).message, tone: 'error' })
    } finally {
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const submitPassword = async () => {
    setPasswordError(null)
    if (passwordForm.next.length < 8) {
      setPasswordError(t('settings.security.minLength'))
      return
    }
    if (passwordForm.next !== passwordForm.confirm) {
      setPasswordError(t('settings.security.mismatch'))
      return
    }
    try {
      await changePassword.mutateAsync({
        current_password: passwordForm.current,
        new_password: passwordForm.next,
      })
      setPasswordForm({ current: '', next: '', confirm: '' })
      toast({ title: t('settings.security.changed'), tone: 'success' })
    } catch (error) {
      setPasswordError((error as Error).message)
    }
  }

  if (settingsQuery.isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-5 pt-32">
        <div className="space-y-4">
          <div className="skeleton h-10 w-48 rounded-xl" />
          <div className="skeleton h-40 rounded-2xl" />
          <div className="skeleton h-56 rounded-2xl" />
        </div>
      </div>
    )
  }

  if (!settings) {
    return (
      <div className="mx-auto max-w-2xl px-5 pt-32">
        <EmptyState
          icon={AlertTriangle}
          title="设置加载失败"
          description={(settingsQuery.error as Error)?.message}
          action={
            <button type="button" onClick={() => settingsQuery.refetch()} className="btn-primary">
              {t('common.retry')}
            </button>
          }
        />
      </div>
    )
  }

  const sections = [
    ['libraries', t('settings.sections.libraries')],
    ['providers', t('settings.sections.providers')],
    ['matching', t('settings.sections.matching')],
    ['player', t('settings.sections.player')],
    ['scanner', t('settings.sections.scanner')],
    ['data', t('settings.sections.data')],
    ['security', t('settings.sections.security')],
    ['about', t('settings.sections.about')],
  ] as const

  return (
    <div className="mx-auto max-w-6xl px-5 pb-28 pt-28 sm:px-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-accent/80">
            CONFIGURATION
          </p>
          <h1 className="mt-2 font-display text-3xl font-black tracking-tight text-white">
            {t('settings.title')}
          </h1>
          <p className="mt-2 text-[13px] text-ink-400">{t('settings.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-ink-500">
          <Database className="h-3.5 w-3.5" />
          {settingsQuery.data?.data_dir}
        </div>
      </div>

      <div className="no-scrollbar sticky top-[68px] z-30 -mx-1 mt-6 flex gap-1 overflow-x-auto border-b border-white/8 bg-[#07080a]/85 px-1 py-2 backdrop-blur-xl">
        {sections.map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            className="shrink-0 rounded-full px-3.5 py-1.5 text-[12px] text-ink-300 transition hover:bg-white/8 hover:text-white"
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-10 space-y-16">
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
                  onDeleted={() => librariesQuery.refetch()}
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

        <Section
          id="providers"
          title={t('settings.sections.providers')}
          description={t('settings.providers.keyHidden')}
          icon={KeyRound}
        >
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card p-5">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-[15px] font-semibold text-white">TMDB</h3>
                <span className="chip">默认主源</span>
              </div>
              <Field label={t('settings.providers.tmdbKey')} hint={t('settings.providers.tmdbHint')}>
                <input
                  className="input"
                  type="password"
                  value={tmdbKey}
                  onChange={(event) => setTmdbKey(event.target.value)}
                  placeholder="未配置"
                  autoComplete="off"
                />
              </Field>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <Field label={t('settings.providers.baseUrl')}>
                  <input className="input" value={tmdbBase} onChange={(event) => setTmdbBase(event.target.value)} />
                </Field>
                <Field label={t('settings.providers.proxy')}>
                  <input
                    className="input"
                    value={tmdbProxy}
                    onChange={(event) => setTmdbProxy(event.target.value)}
                    placeholder={t('settings.providers.proxyPlaceholder')}
                  />
                </Field>
              </div>
              <div className="mt-4 flex items-center gap-2">
                <button type="button" onClick={saveTmdb} disabled={patchSettings.isPending} className="btn-primary px-5 py-2.5 text-[13px]">
                  {t('common.save')}
                </button>
                <button type="button" onClick={() => runTest('tmdb')} disabled={providerTest.isPending} className="btn-ghost gap-1.5 px-4 py-2.5 text-[12px]">
                  {providerTest.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
                  {providerTest.isPending ? t('settings.providers.testing') : t('settings.providers.test')}
                </button>
              </div>
              <TestBadge result={testResult.tmdb} />
            </div>

            <div className="card p-5">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-[15px] font-semibold text-white">TVDB</h3>
                <span className="chip">第二源</span>
              </div>
              <Field label={t('settings.providers.tvdbKey')} hint={t('settings.providers.tvdbHint')}>
                <input
                  className="input"
                  type="password"
                  value={tvdbKey}
                  onChange={(event) => setTvdbKey(event.target.value)}
                  placeholder="未配置"
                  autoComplete="off"
                />
              </Field>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <Field label={t('settings.providers.tvdbPin')}>
                  <input
                    className="input"
                    type="password"
                    value={tvdbPin}
                    onChange={(event) => setTvdbPin(event.target.value)}
                    placeholder="可留空"
                    autoComplete="off"
                  />
                </Field>
                <Field label={t('settings.providers.baseUrl')}>
                  <input className="input" value={tvdbBase} onChange={(event) => setTvdbBase(event.target.value)} />
                </Field>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <Field label={t('settings.providers.proxy')}>
                  <input
                    className="input"
                    value={tvdbProxy}
                    onChange={(event) => setTvdbProxy(event.target.value)}
                    placeholder={t('settings.providers.proxyPlaceholder')}
                  />
                </Field>
                <Field label={t('settings.providers.seasonType')}>
                  <select
                    className="input"
                    value={seasonType}
                    onChange={(event) => setSeasonType(event.target.value)}
                  >
                    <option value="default">{t('library.fields.seasonTypeDefault')}</option>
                    <option value="absolute">{t('library.fields.seasonTypeAbsolute')}</option>
                    <option value="dvd">{t('library.fields.seasonTypeDvd')}</option>
                  </select>
                </Field>
              </div>
              <div className="mt-4 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() =>
                    save({
                      scraper: {
                        tvdb: {
                          api_key: tvdbKey,
                          pin: tvdbPin,
                          base_url: tvdbBase || undefined,
                          proxy: tvdbProxy,
                          season_type: seasonType,
                        },
                      },
                    })
                  }
                  disabled={patchSettings.isPending}
                  className="btn-primary px-5 py-2.5 text-[13px]"
                >
                  {t('common.save')}
                </button>
                <button type="button" onClick={() => runTest('tvdb')} disabled={providerTest.isPending} className="btn-ghost gap-1.5 px-4 py-2.5 text-[12px]">
                  {providerTest.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
                  {providerTest.isPending ? t('settings.providers.testing') : t('settings.providers.test')}
                </button>
              </div>
              <TestBadge result={testResult.tvdb} />
            </div>
          </div>

          <div className="card p-5">
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label={t('settings.providers.language')}>
                <select className="input" value={language} onChange={(event) => setLanguage(event.target.value)}>
                  <option value="zh-CN">简体中文（zh-CN）</option>
                  <option value="zh-TW">繁體中文（zh-TW）</option>
                  <option value="en-US">English（en-US）</option>
                  <option value="ja-JP">日本語（ja-JP）</option>
                </select>
              </Field>
              <div className="flex items-end">
                <button
                  type="button"
                  onClick={() => save({ scraper: { language } })}
                  disabled={patchSettings.isPending}
                  className="btn-ghost w-full justify-center py-3"
                >
                  {t('common.save')}
                </button>
              </div>
            </div>
          </div>
        </Section>

        <Section id="matching" title={t('settings.sections.matching')} icon={Wand2}>
          <div className="card p-5">
            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <label className="label">
                  {t('settings.matching.threshold')}
                  <span className="ml-2 font-mono text-accent">{Number(threshold).toFixed(2)}</span>
                </label>
                <input
                  type="range"
                  min="0.5"
                  max="0.95"
                  step="0.01"
                  value={threshold}
                  onChange={(event) => setThreshold(event.target.value)}
                  className="w-full accent-[#e8b06a]"
                />
                <p className="mt-1.5 text-[11px] text-ink-500">{t('settings.matching.thresholdHint')}</p>
              </div>
              <Field label={t('settings.matching.autoRefreshDays')} hint={t('settings.matching.autoRefreshHint')}>
                <input
                  className="input"
                  inputMode="numeric"
                  value={refreshDays}
                  onChange={(event) => setRefreshDays(event.target.value)}
                />
              </Field>
            </div>
            <div className="mt-6 space-y-4">
              <div>
                <label className="label">{t('settings.matching.priority')}</label>
                <p className="mb-3 text-[11px] text-ink-500">{t('settings.matching.priorityHint')}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  {typeOrder.map((type) => (
                    <div key={type} className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
                      <p className="mb-2 text-[12px] font-medium text-ink-200">{t(`library.type.${type}`)}</p>
                      <div className="flex items-center gap-2">
                        {[0, 1].map((index) => (
                          <select
                            key={index}
                            className="input py-1.5 text-[12px]"
                            value={priority[type]?.[index] || ''}
                            onChange={(event) => {
                              const value = event.target.value
                              const next = [...(priority[type] || [])]
                              if (!value) {
                                next.splice(index, 1)
                              } else {
                                next[index] = value
                              }
                              setPriority((prev) => ({
                                ...prev,
                                [type]: next.filter(Boolean),
                              }))
                            }}
                          >
                            <option value="">—</option>
                            <option value="tmdb">TMDB</option>
                            <option value="tvdb">TVDB</option>
                          </select>
                        ))}
                        {priority[type]?.length ? (
                          <span className="text-[10.5px] text-ink-500">
                            {priority[type].join(' → ')}
                          </span>
                        ) : (
                          <span className="text-[10.5px] text-ink-500">不刮削</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="mt-5">
              <button
                type="button"
                onClick={() =>
                  save({
                    scraper: {
                      match_threshold: Number(threshold),
                      auto_refresh_days: Number(refreshDays) || 0,
                      provider_priority: priority,
                    },
                  })
                }
                disabled={patchSettings.isPending}
                className="btn-primary px-5 py-2.5 text-[13px]"
              >
                {t('settings.matching.save')}
              </button>
            </div>
          </div>
        </Section>

        <Section id="player" title={t('settings.sections.player')} icon={Play}>
          <div className="card p-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t('settings.player.mode')} hint={t('settings.player.modeHint')}>
                <select className="input" value={playerMode} onChange={(event) => setPlayerMode(event.target.value)}>
                  <option value="builtin">{t('settings.player.builtin')}</option>
                  <option value="external_mpv">{t('settings.player.externalMpv')}</option>
                  <option value="browser_intent">{t('settings.player.browserIntent')}</option>
                  <option value="desktop_mpv">{t('settings.player.desktopMpv')}</option>
                  <option value="copy">{t('settings.player.copy')}</option>
                  <option value="auto">{t('settings.player.auto')}</option>
                </select>
              </Field>
              <Field label={t('settings.player.mpvPath')}>
                <input className="input" value={mpvPath} onChange={(event) => setMpvPath(event.target.value)} />
              </Field>
              <Field label={t('settings.player.progressInterval')} hint={t('settings.player.progressIntervalHint')}>
                <input
                  className="input"
                  inputMode="numeric"
                  value={progressInterval}
                  onChange={(event) => setProgressInterval(event.target.value)}
                />
              </Field>
              <Field label={t('settings.player.tokenTtl')} hint={t('settings.player.tokenTtlHint')}>
                <input
                  className="input"
                  inputMode="numeric"
                  value={tokenTtl}
                  onChange={(event) => setTokenTtl(event.target.value)}
                />
              </Field>
            </div>
            <div className="mt-4">
              <Field label={t('settings.player.headers')} hint={t('settings.player.headersHint')}>
                <textarea
                  className="input min-h-[92px] font-mono text-[12px] leading-relaxed"
                  value={playHeadersGlobal}
                  onChange={(event) => setPlayHeadersGlobal(event.target.value)}
                  placeholder={'User-Agent: pan.baidu.com\nReferer: https://pan.baidu.com/'}
                />
              </Field>
            </div>
            <div className="mt-4">
              <Field label={t('settings.player.extraArgs')}>
                <textarea
                  className="input min-h-[90px] font-mono text-[12px] leading-relaxed"
                  value={mpvArgs}
                  onChange={(event) => setMpvArgs(event.target.value)}
                />
              </Field>
            </div>
            <label className="mt-4 flex items-center gap-2.5 text-[12.5px] text-ink-200">
              <input
                type="checkbox"
                checked={fallbackOnError}
                onChange={(event) => setFallbackOnError(event.target.checked)}
                className="h-4 w-4 accent-[#e8b06a]"
              />
              {t('settings.player.fallback')}
            </label>
            <label className="mt-3 flex items-center gap-2.5 text-[12.5px] text-ink-200">
              <input
                type="checkbox"
                checked={enableProgress}
                onChange={(event) => setEnableProgress(event.target.checked)}
                className="h-4 w-4 accent-[#e8b06a]"
              />
              {t('settings.player.enableProgress')}
            </label>

            <div className="mt-5 rounded-2xl border border-white/8 bg-white/[0.02] p-4">
              <p className="flex items-center gap-2 text-[12.5px] font-medium text-ink-100">
                <Tv className="h-4 w-4 text-accent" />
                {t('settings.player.companion')}
              </p>
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-400">
                {companion?.version?.()
                  ? t('settings.player.companionVersion', { version: companion.version() })
                  : t('settings.player.companionNotInstalled')}
              </p>
              {companion?.openSettings ? (
                <button
                  type="button"
                  onClick={() => companion.openSettings?.()}
                  className="btn-ghost mt-3 px-4 py-2 text-[12px]"
                >
                  {t('settings.player.companionOpen')}
                </button>
              ) : (
                <p className="mt-1.5 text-[11px] text-ink-500">{t('settings.player.companionHint')}</p>
              )}
            </div>

            <div className="mt-5">
              <button
                type="button"
                onClick={() =>
                  save({
                    player: {
                      mode: playerMode,
                      progress_interval_ms: Number(progressInterval) || 5000,
                      play_token_ttl_hours: Number(tokenTtl) || 12,
                      fallback_on_error: fallbackOnError,
                      play_headers: textToHeaders(playHeadersGlobal),
                      mpv_path: mpvPath,
                      mpv_extra_args: mpvArgs.split('\n').map((line) => line.trim()).filter(Boolean),
                      enable_progress: enableProgress,
                    },
                  })
                }
                disabled={patchSettings.isPending}
                className="btn-primary px-5 py-2.5 text-[13px]"
              >
                {t('common.save')}
              </button>
            </div>
          </div>
        </Section>

        <Section id="scanner" title={t('settings.sections.scanner')} icon={ScanLine}>
          <div className="card p-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t('settings.scanner.ignore')}>
                <textarea
                  className="input min-h-[100px] font-mono text-[12px]"
                  value={ignore}
                  onChange={(event) => setIgnore(event.target.value)}
                />
              </Field>
              <div className="space-y-4">
                <Field label={t('settings.scanner.maxDepth')}>
                  <input className="input" inputMode="numeric" value={maxDepth} onChange={(event) => setMaxDepth(event.target.value)} />
                </Field>
                <label className="flex items-center gap-2.5 text-[12.5px] text-ink-200">
                  <input
                    type="checkbox"
                    checked={followSymlinks}
                    onChange={(event) => setFollowSymlinks(event.target.checked)}
                    className="h-4 w-4 accent-[#e8b06a]"
                  />
                  {t('settings.scanner.followSymlinks')}
                </label>
              </div>
            </div>
            <div className="mt-5">
              <button
                type="button"
                onClick={() =>
                  save({
                    scanner: {
                      ignore: ignore.split('\n').map((line) => line.trim()).filter(Boolean),
                      follow_symlinks: followSymlinks,
                      max_depth: Number(maxDepth) || 6,
                    },
                  })
                }
                disabled={patchSettings.isPending}
                className="btn-primary px-5 py-2.5 text-[13px]"
              >
                {t('settings.scanner.save')}
              </button>
            </div>
          </div>
        </Section>

        <Section id="data" title={t('settings.sections.data')} icon={Database}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="card p-5">
              <h3 className="text-[14px] font-semibold text-white">{t('settings.data.export')}</h3>
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-400">
                {t('settings.data.exportHint')}
              </p>
              <button type="button" onClick={doExport} disabled={exportData.isPending} className="btn-ghost mt-4 gap-1.5">
                {exportData.isPending ? <Spinner className="h-4 w-4" /> : <Download className="h-4 w-4" />}
                {t('settings.data.export')}
              </button>
            </div>
            <div className="card p-5">
              <h3 className="text-[14px] font-semibold text-white">{t('settings.data.import')}</h3>
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-400">
                {t('settings.data.importHint')}
              </p>
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                disabled={importData.isPending}
                className="btn-ghost mt-4 gap-1.5"
              >
                {importData.isPending ? <Spinner className="h-4 w-4" /> : <Upload className="h-4 w-4" />}
                {t('settings.data.import')}
              </button>
              <input
                ref={fileInput}
                type="file"
                accept="application/json"
                hidden
                onChange={(event) => doImport(event.target.files?.[0])}
              />
            </div>
          </div>
        </Section>

        <Section id="security" title={t('settings.sections.security')} icon={ShieldCheck}>
          <div className="card max-w-2xl p-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Field label={t('settings.security.currentPassword')}>
                  <input
                    className="input"
                    type="password"
                    autoComplete="current-password"
                    value={passwordForm.current}
                    onChange={(event) => setPasswordForm((prev) => ({ ...prev, current: event.target.value }))}
                  />
                </Field>
              </div>
              <Field label={t('settings.security.newPassword')}>
                <input
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  value={passwordForm.next}
                  onChange={(event) => setPasswordForm((prev) => ({ ...prev, next: event.target.value }))}
                />
              </Field>
              <Field label={t('settings.security.confirmPassword')}>
                <input
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  value={passwordForm.confirm}
                  onChange={(event) => setPasswordForm((prev) => ({ ...prev, confirm: event.target.value }))}
                />
              </Field>
            </div>
            {passwordError ? (
              <p className="mt-3 flex items-center gap-1.5 text-[11.5px] text-rose-300">
                <AlertTriangle className="h-3.5 w-3.5" />
                {passwordError}
              </p>
            ) : null}
            <button
              type="button"
              onClick={submitPassword}
              disabled={changePassword.isPending}
              className="btn-primary mt-4 gap-1.5 px-5 py-2.5 text-[13px]"
            >
              <Lock className="h-3.5 w-3.5" />
              {t('settings.security.change')}
            </button>
          </div>
        </Section>

        <Section id="about" title={t('settings.sections.about')} icon={CheckCircle2}>
          <div className="card space-y-3 p-5 text-[12.5px] text-ink-300">
            <div className="flex flex-wrap justify-between gap-2">
              <span>{t('settings.about.version')}</span>
              <span className="font-mono">{settingsQuery.data?.version}</span>
            </div>
            <div className="flex flex-wrap justify-between gap-2">
              <span>{t('settings.about.dataDir')}</span>
              <span className="break-all font-mono text-[11.5px]">{settingsQuery.data?.data_dir}</span>
            </div>
            <div className="flex flex-wrap justify-between gap-2">
              <span>API 文档</span>
              <a href="/docs" target="_blank" rel="noreferrer" className="text-accent hover:underline">
                /docs
              </a>
            </div>
            <p className="border-t border-white/8 pt-3 text-[11px] leading-relaxed text-ink-500">
              {t('settings.about.tmdbNotice')}
            </p>
            <p className="text-[11px] leading-relaxed text-ink-500">{t('settings.about.tvHint')}</p>
          </div>
        </Section>
      </div>

      <Modal
        open={libraryModal}
        onClose={() => setLibraryModal(false)}
        title={editing ? t('library.edit') : t('library.add')}
        width="lg"
        footer={
          <>
            <button type="button" onClick={() => setLibraryModal(false)} className="btn-ghost">
              {t('common.cancel')}
            </button>
            <button
              type="button"
              onClick={submitLibrary}
              disabled={createLibrary.isPending || updateLibrary.isPending}
              className="btn-primary px-6 py-2.5 disabled:opacity-60"
            >
              {createLibrary.isPending || updateLibrary.isPending ? t('common.saving') : t('common.save')}
            </button>
          </>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('library.fields.name')}>
            <input
              className="input"
              value={libraryForm.name}
              onChange={(event) => setLibraryForm((prev) => ({ ...prev, name: event.target.value }))}
              placeholder={t('library.fields.namePlaceholder')}
            />
          </Field>
          <Field label={t('library.fields.type')}>
            <select
              className="input"
              value={libraryForm.type}
              onChange={(event) => setLibraryForm((prev) => ({ ...prev, type: event.target.value as LibraryType }))}
            >
              {typeOrder.map((type) => (
                <option key={type} value={type}>
                  {t(`library.type.${type}`)}
                </option>
              ))}
            </select>
          </Field>
          <div className="sm:col-span-2">
            <Field label={t('library.fields.rootPath')} hint="必须是容器内可访问的绝对路径，例如 /media/strm/movies">
              <input
                className="input font-mono text-[13px]"
                value={libraryForm.root_path}
                onChange={(event) => setLibraryForm((prev) => ({ ...prev, root_path: event.target.value }))}
                placeholder={t('library.fields.rootPathPlaceholder')}
              />
            </Field>
          </div>
          <Field label={t('library.fields.scanCron')} hint={t('library.fields.scanCronPlaceholder')}>
            <input
              className="input font-mono text-[13px]"
              value={libraryForm.scan_cron}
              onChange={(event) => setLibraryForm((prev) => ({ ...prev, scan_cron: event.target.value }))}
              placeholder="0 3 * * *"
            />
          </Field>
          <Field label={t('library.fields.seasonType')}>
            <select
              className="input"
              value={libraryForm.tvdb_season_type}
              onChange={(event) => setLibraryForm((prev) => ({ ...prev, tvdb_season_type: event.target.value }))}
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
                value={libraryForm.template}
                onChange={(event) => setLibraryForm((prev) => ({ ...prev, template: event.target.value }))}
                placeholder={t('library.fields.templatePlaceholder')}
              />
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label={t('library.fields.priority')} hint={t('library.fields.priorityHint')}>
              <div className="flex flex-wrap gap-2">
                {['tmdb', 'tvdb'].map((provider) => {
                  const active = libraryForm.priority.includes(provider)
                  return (
                    <button
                      key={provider}
                      type="button"
                      onClick={() =>
                        setLibraryForm((prev) => ({
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
                {libraryForm.priority.length ? (
                  <span className="self-center text-[11px] text-ink-500">
                    {libraryForm.priority.join(' → ')}
                  </span>
                ) : null}
              </div>
            </Field>
          </div>
          <div className="sm:col-span-2">
            <Field label={t('library.fields.playHeaders')} hint={t('library.fields.playHeadersHint')}>
              <textarea
                className="input min-h-[80px] font-mono text-[12px] leading-relaxed"
                value={libraryForm.play_headers}
                onChange={(event) =>
                  setLibraryForm((prev) => ({ ...prev, play_headers: event.target.value }))
                }
                placeholder={t('library.fields.playHeadersPlaceholder')}
              />
            </Field>
          </div>
          <label className="flex items-center gap-2.5 text-[12.5px] text-ink-200">
            <input
              type="checkbox"
              checked={libraryForm.auto_scrape}
              onChange={(event) => setLibraryForm((prev) => ({ ...prev, auto_scrape: event.target.checked }))}
              className="h-4 w-4 accent-[#e8b06a]"
            />
            {t('library.fields.autoScrape')}
          </label>
          <label className="flex items-center gap-2.5 text-[12.5px] text-ink-200">
            <input
              type="checkbox"
              checked={libraryForm.enabled}
              onChange={(event) => setLibraryForm((prev) => ({ ...prev, enabled: event.target.checked }))}
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
    </div>
  )
}

function TestBadge({
  result,
}: {
  result?: { ok: boolean; message: string; latency: number }
}) {
  if (!result) return null
  return (
    <p
      className={`mt-3 flex items-center gap-1.5 text-[11.5px] ${
        result.ok ? 'text-emerald-300' : 'text-rose-300'
      }`}
    >
      {result.ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
      {result.ok
        ? t('settings.providers.testOk', { ms: result.latency })
        : t('settings.providers.testFailed', { message: result.message })}
    </p>
  )
}
