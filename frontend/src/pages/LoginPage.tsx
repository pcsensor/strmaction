import { FormEvent, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Clapperboard, LockKeyhole, PlayCircle, ShieldCheck } from 'lucide-react'
import { useAuthState, useLogin } from '../api/hooks'
import { Logo } from '../components/TopBar'
import { t } from '../i18n/zh-CN'

export function LoginPage() {
  const login = useLogin()
  const auth = useAuthState()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      await login.mutateAsync({ username: username.trim(), password })
      const target = (location.state as { from?: string } | null)?.from || '/'
      navigate(target, { replace: true })
    } catch (err) {
      const message = (err as Error).message
      setError(message)
    }
  }

  return (
    <div className="safe-top safe-bottom relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
      <div className="absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-[radial-gradient(90%_80%_at_20%_0%,rgba(232,176,106,0.18),transparent_60%),radial-gradient(80%_70%_at_90%_20%,rgba(64,96,180,0.16),transparent_55%),#07080a]" />
        <div className="grain absolute inset-0" />
      </div>

      <div className="grid w-full max-w-5xl items-center gap-10 lg:grid-cols-2">
        <div className="hidden lg:block">
          <Logo />
          <h1 className="mt-8 font-display text-4xl font-black leading-tight tracking-tight text-white">
            把播放从
            <br />
            媒体服务器里剥离。
          </h1>
          <p className="mt-4 max-w-sm text-[14px] leading-relaxed text-ink-300">
            StrmAction 扫描你的 .strm 目录，自己刮削元数据、组织剧集，并在点播放时把地址交给 mpv。
            不转码、不代理、不消耗服务器带宽。
          </p>
          <div className="mt-8 space-y-3">
            {[
              [PlayCircle, 'App 内部播放，或复制所选版本链接'],
              [Clapperboard, '电影 / 剧集 / 家庭视频 / 课程'],
              [ShieldCheck, '播放地址视为凭证，全程鉴权'],
            ].map(([Icon, text]) => {
              const Component = Icon as typeof PlayCircle
              return (
                <div key={text as string} className="flex items-center gap-3 text-[12.5px] text-ink-300">
                  <span className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 bg-white/5 text-accent">
                    <Component className="h-4 w-4" />
                  </span>
                  {text as string}
                </div>
              )
            })}
          </div>
        </div>

        <div className="mx-auto w-full max-w-[420px]">
          <div className="mb-6 flex justify-center lg:hidden">
            <Logo />
          </div>
          <div className="rounded-3xl border border-white/10 bg-[#0c0f15]/85 p-7 shadow-lift backdrop-blur-2xl sm:p-8">
            <div className="mb-6">
              <span className="grid h-10 w-10 place-items-center rounded-xl border border-white/10 bg-white/5 text-accent">
                <LockKeyhole className="h-4.5 w-4.5" />
              </span>
              <h2 className="mt-4 font-display text-2xl font-bold tracking-tight text-white">
                {t('login.title')}
              </h2>
              <p className="mt-1.5 text-[13px] text-ink-400">{t('login.subtitle')}</p>
            </div>

            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="label" htmlFor="username">
                  {t('login.username')}
                </label>
                <input
                  id="username"
                  className="input"
                  autoComplete="username"
                  autoFocus
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                />
              </div>
              <div>
                <label className="label" htmlFor="password">
                  {t('login.password')}
                </label>
                <input
                  id="password"
                  type="password"
                  className="input"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </div>

              {auth.data?.needs_setup ? (
                <p className="rounded-xl border border-amber-400/25 bg-amber-400/10 px-3 py-2 text-[12px] text-amber-200">
                  {t('login.setupRequired')}
                </p>
              ) : null}
              {error ? (
                <p className="rounded-xl border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-[12px] text-rose-200">
                  {error}
                </p>
              ) : null}

              <button
                type="submit"
                disabled={login.isPending || !username.trim() || !password}
                className="btn-primary w-full py-3.5 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {login.isPending ? t('login.submitting') : t('login.submit')}
              </button>
            </form>

            <p className="mt-6 text-center text-[10.5px] leading-relaxed text-ink-600">
              {t('app.footer')}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
