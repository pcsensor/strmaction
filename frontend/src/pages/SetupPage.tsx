import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Clapperboard,
  FolderPlus,
  KeyRound,
  LockKeyhole,
  Sparkles,
} from 'lucide-react'
import type { LibraryType } from '../api/types'
import {
  useAuthState,
  useCreateLibrary,
  useLibraryTask,
  usePatchSettings,
  useProviderTest,
  useSetup,
} from '../api/hooks'
import { Logo } from '../components/TopBar'
import { Spinner } from '../components/Spinner'
import { useToast } from '../store/ui'
import { t } from '../i18n/zh-CN'

const ONBOARDING_KEY = 'strmaction:onboarding'

export function SetupPage() {
  const auth = useAuthState()
  const setup = useSetup()
  const patchSettings = usePatchSettings()
  const providerTest = useProviderTest()
  const createLibrary = useCreateLibrary()
  const libraryTask = useLibraryTask()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()

  const [step, setStep] = useState(1)
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [tmdbKey, setTmdbKey] = useState('')
  const [tvdbKey, setTvdbKey] = useState('')
  const [tvdbPin, setTvdbPin] = useState('')
  const [test, setTest] = useState<Record<string, { ok: boolean; message: string }>>({})
  const [library, setLibrary] = useState({
    name: '',
    root_path: '/media/strm',
    type: 'movie' as LibraryType,
    scan_cron: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (auth.data && !auth.data.needs_setup && step === 1) {
      setStep(2)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.data])

  const submitPassword = async () => {
    setError(null)
    if (password.length < 8 || /^\d+$/.test(password)) {
      setError(t('setup.password.weak'))
      return
    }
    if (password !== confirm) {
      setError(t('setup.password.mismatch'))
      return
    }
    setBusy(true)
    sessionStorage.setItem(ONBOARDING_KEY, '1')
    try {
      await setup.mutateAsync({ password, username: username.trim() || 'admin' })
      setStep(2)
    } catch (err) {
      sessionStorage.removeItem(ONBOARDING_KEY)
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const saveProviders = async (skip = false) => {
    setError(null)
    setBusy(true)
    try {
      if (!skip && (tmdbKey || tvdbKey)) {
        await patchSettings.mutateAsync({
          scraper: {
            tmdb: { api_key: tmdbKey },
            tvdb: { api_key: tvdbKey, pin: tvdbPin },
          },
        })
        const results: Record<string, { ok: boolean; message: string }> = {}
        if (tmdbKey) {
          try {
            const result = await providerTest.mutateAsync('tmdb')
            results.tmdb = { ok: result.ok, message: result.message }
          } catch (err) {
            results.tmdb = { ok: false, message: (err as Error).message }
          }
        }
        if (tvdbKey) {
          try {
            const result = await providerTest.mutateAsync('tvdb')
            results.tvdb = { ok: result.ok, message: result.message }
          } catch (err) {
            results.tvdb = { ok: false, message: (err as Error).message }
          }
        }
        setTest(results)
      }
      setStep(3)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const createAndScan = async () => {
    setError(null)
    if (!library.name.trim()) {
      setError(t('library.errors.nameRequired'))
      return
    }
    if (!library.root_path.trim().startsWith('/')) {
      setError(t('library.errors.rootRequired'))
      return
    }
    setBusy(true)
    try {
      const created = await createLibrary.mutateAsync({
        name: library.name.trim(),
        root_path: library.root_path.trim(),
        type: library.type,
        scan_cron: library.scan_cron.trim() || null,
      })
      await libraryTask.mutateAsync({ id: created.id, action: 'scan' })
      sessionStorage.removeItem(ONBOARDING_KEY)
      queryClient.invalidateQueries()
      toast({ title: t('setup.library.created'), tone: 'success' })
      navigate('/', { replace: true })
    } catch (err) {
      setError((err as Error).message || t('setup.library.failed'))
    } finally {
      setBusy(false)
    }
  }

  const finish = () => {
    sessionStorage.removeItem(ONBOARDING_KEY)
    queryClient.invalidateQueries()
    navigate('/', { replace: true })
  }

  const steps = [
    { label: t('setup.steps.password'), icon: LockKeyhole },
    { label: t('setup.steps.providers'), icon: KeyRound },
    { label: t('setup.steps.library'), icon: FolderPlus },
  ]

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden">
      <div className="absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-[radial-gradient(80%_60%_at_15%_0%,rgba(232,176,106,0.16),transparent_58%),radial-gradient(70%_60%_at_90%_10%,rgba(64,96,180,0.14),transparent_55%),#07080a]" />
        <div className="grain absolute inset-0" />
      </div>

      <header className="flex h-[76px] items-center justify-between px-5 sm:px-10">
        <Logo />
        <span className="text-[11px] text-ink-500">{t('setup.step', { current: step, total: 3 })}</span>
      </header>

      <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-5 pb-16 pt-4 sm:px-10">
        <div className="mb-8 flex items-center gap-2">
          {steps.map((item, index) => {
            const number = index + 1
            const done = step > number
            const active = step === number
            return (
              <div key={item.label} className="flex flex-1 items-center gap-2">
                <div
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-[12px] font-semibold transition ${
                    done
                      ? 'border-emerald-400/40 bg-emerald-400/15 text-emerald-300'
                      : active
                        ? 'border-accent/50 bg-accent/15 text-accent'
                        : 'border-white/10 bg-white/[0.03] text-ink-500'
                  }`}
                >
                  {done ? <Check className="h-4 w-4" /> : number}
                </div>
                <span className={`hidden text-[12px] sm:block ${active ? 'text-white' : 'text-ink-500'}`}>
                  {item.label}
                </span>
                {index < steps.length - 1 ? (
                  <div className={`h-px flex-1 ${done ? 'bg-emerald-400/40' : 'bg-white/10'}`} />
                ) : null}
              </div>
            )
          })}
        </div>

        <motion.div
          key={step}
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          className="rounded-3xl border border-white/10 bg-[#0b0e14]/85 p-6 shadow-lift backdrop-blur-2xl sm:p-9"
        >
          {step === 1 ? (
            <>
              <div className="mb-7">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-accent/80">
                  {t('setup.welcome')}
                </p>
                <h1 className="mt-2 font-display text-3xl font-black tracking-tight text-white">
                  {t('setup.password.title')}
                </h1>
                <p className="mt-2 max-w-xl text-[13px] leading-relaxed text-ink-400">
                  {t('setup.password.desc')}
                </p>
              </div>
              <div className="grid max-w-xl gap-4">
                <div>
                  <label className="label">{t('setup.password.username')}</label>
                  <input className="input" value={username} onChange={(event) => setUsername(event.target.value)} />
                </div>
                <div>
                  <label className="label">{t('setup.password.password')}</label>
                  <input
                    className="input"
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                  <p className="mt-1.5 text-[11px] text-ink-500">{t('setup.password.hint')}</p>
                </div>
                <div>
                  <label className="label">{t('setup.password.confirm')}</label>
                  <input
                    className="input"
                    type="password"
                    autoComplete="new-password"
                    value={confirm}
                    onChange={(event) => setConfirm(event.target.value)}
                  />
                </div>
              </div>
              {error ? <ErrorLine message={error} /> : null}
              <div className="mt-7">
                <button
                  type="button"
                  onClick={submitPassword}
                  disabled={busy || setup.isPending}
                  className="btn-primary gap-2 px-7 py-3.5"
                >
                  {busy ? <Spinner className="h-4 w-4" /> : null}
                  {t('setup.password.next')}
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </>
          ) : null}

          {step === 2 ? (
            <>
              <div className="mb-7">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-accent/80">
                  {t('setup.steps.providers')}
                </p>
                <h1 className="mt-2 font-display text-3xl font-black tracking-tight text-white">
                  {t('setup.providers.title')}
                </h1>
                <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-ink-400">
                  {t('setup.providers.desc')}
                </p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-[13.5px] font-semibold text-white">TMDB</span>
                    <Sparkles className="h-4 w-4 text-accent" />
                  </div>
                  <input
                    className="input"
                    type="password"
                    placeholder="TMDB API Key"
                    value={tmdbKey}
                    onChange={(event) => setTmdbKey(event.target.value)}
                    autoComplete="off"
                  />
                  <p className="mt-2 text-[10.5px] leading-relaxed text-ink-500">
                    themoviedb.org → 设置 → API → 创建 v3 Key
                  </p>
                  {test.tmdb ? <TestLine ok={test.tmdb.ok} message={test.tmdb.message} /> : null}
                </div>
                <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-[13.5px] font-semibold text-white">TVDB</span>
                    <Sparkles className="h-4 w-4 text-accent" />
                  </div>
                  <input
                    className="input"
                    type="password"
                    placeholder="TVDB API Key"
                    value={tvdbKey}
                    onChange={(event) => setTvdbKey(event.target.value)}
                    autoComplete="off"
                  />
                  <input
                    className="input mt-2"
                    type="password"
                    placeholder="TVDB PIN（可选）"
                    value={tvdbPin}
                    onChange={(event) => setTvdbPin(event.target.value)}
                    autoComplete="off"
                  />
                  {test.tvdb ? <TestLine ok={test.tvdb.ok} message={test.tvdb.message} /> : null}
                </div>
              </div>
              <p className="mt-3 text-[11px] text-ink-500">{t('setup.providers.hint')}</p>
              {error ? <ErrorLine message={error} /> : null}
              <div className="mt-7 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="btn-ghost gap-1.5"
                  disabled={busy}
                >
                  <ArrowLeft className="h-4 w-4" />
                  {t('setup.back')}
                </button>
                <button
                  type="button"
                  onClick={() => saveProviders(false)}
                  disabled={busy}
                  className="btn-primary gap-2 px-6 py-3"
                >
                  {busy ? <Spinner className="h-4 w-4" /> : <Check className="h-4 w-4" />}
                  {busy ? t('setup.providers.applying') : t('setup.providers.apply')}
                </button>
                <button type="button" onClick={() => saveProviders(true)} disabled={busy} className="btn-ghost">
                  {t('setup.providers.later')}
                </button>
              </div>
            </>
          ) : null}

          {step === 3 ? (
            <>
              <div className="mb-7">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-accent/80">
                  {t('setup.steps.library')}
                </p>
                <h1 className="mt-2 font-display text-3xl font-black tracking-tight text-white">
                  {t('setup.library.title')}
                </h1>
                <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-ink-400">
                  {t('setup.library.desc')}
                </p>
              </div>
              <div className="grid max-w-2xl gap-4">
                <div>
                  <label className="label">{t('setup.library.name')}</label>
                  <input
                    className="input"
                    placeholder="例如：电影 / 剧集 / 动漫"
                    value={library.name}
                    onChange={(event) => setLibrary((prev) => ({ ...prev, name: event.target.value }))}
                  />
                </div>
                <div>
                  <label className="label">{t('setup.library.rootPath')}</label>
                  <input
                    className="input font-mono text-[13px]"
                    placeholder="/media/strm/movies"
                    value={library.root_path}
                    onChange={(event) => setLibrary((prev) => ({ ...prev, root_path: event.target.value }))}
                  />
                  <p className="mt-1.5 text-[11px] text-ink-500">
                    该目录必须已经挂载到 StrmAction 容器内。
                  </p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <label className="label">{t('setup.library.type')}</label>
                    <select
                      className="input"
                      value={library.type}
                      onChange={(event) =>
                        setLibrary((prev) => ({ ...prev, type: event.target.value as LibraryType }))
                      }
                    >
                      <option value="movie">电影</option>
                      <option value="tv">电视剧</option>
                      <option value="home">家庭视频</option>
                      <option value="course">课程</option>
                    </select>
                  </div>
                  <div>
                    <label className="label">{t('setup.library.scanCron')}</label>
                    <input
                      className="input font-mono text-[13px]"
                      placeholder="0 3 * * *"
                      value={library.scan_cron}
                      onChange={(event) => setLibrary((prev) => ({ ...prev, scan_cron: event.target.value }))}
                    />
                  </div>
                </div>
              </div>
              {error ? <ErrorLine message={error} /> : null}
              <div className="mt-7 flex flex-wrap items-center gap-3">
                <button type="button" onClick={() => setStep(2)} className="btn-ghost gap-1.5" disabled={busy}>
                  <ArrowLeft className="h-4 w-4" />
                  {t('setup.back')}
                </button>
                <button
                  type="button"
                  onClick={createAndScan}
                  disabled={busy}
                  className="btn-primary gap-2 px-6 py-3"
                >
                  {busy ? <Spinner className="h-4 w-4" /> : <Clapperboard className="h-4 w-4" />}
                  {busy ? t('setup.library.submitting') : t('setup.library.submit')}
                </button>
                <button type="button" onClick={finish} className="btn-ghost">
                  {t('setup.finish')}
                </button>
              </div>
            </>
          ) : null}
        </motion.div>

        <p className="mt-6 text-center text-[10.5px] leading-relaxed text-ink-600">
          {t('app.footer')}
        </p>
      </div>
    </div>
  )
}

function ErrorLine({ message }: { message: string }) {
  return (
    <p className="mt-4 rounded-xl border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-[12px] text-rose-200">
      {message}
    </p>
  )
}

function TestLine({ ok, message }: { ok: boolean; message: string }) {
  return (
    <p className={`mt-2 flex items-center gap-1.5 text-[10.5px] ${ok ? 'text-emerald-300' : 'text-rose-300'}`}>
      {ok ? <CheckCircle2 className="h-3 w-3" /> : <Sparkles className="h-3 w-3" />}
      {message}
    </p>
  )
}
