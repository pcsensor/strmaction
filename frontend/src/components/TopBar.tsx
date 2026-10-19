import { NavLink, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { AlertTriangle, Clapperboard, LogOut, Search, Settings } from 'lucide-react'
import { useHome, useLogout } from '../api/hooks'
import { useAuthState } from '../api/hooks'
import { useScrollDirection } from '../hooks/useTVMode'
import { t } from '../i18n/zh-CN'

const links = [
  { to: '/', label: t('nav.home'), end: true },
  { to: '/search', label: t('nav.search') },
  { to: '/tasks', label: t('nav.tasks') },
  { to: '/settings', label: t('nav.settings') },
]

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className="relative grid h-9 w-9 place-items-center overflow-hidden rounded-xl bg-gradient-to-br from-accent-soft via-accent to-accent-deep shadow-[0_8px_24px_-10px_rgba(232,176,106,0.8)]">
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-ink-950" fill="none">
          <path d="M9 6.5v11l8.5-5.5L9 6.5Z" fill="currentColor" />
          <path d="M4.5 5.5v13" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      </span>
      {compact ? null : (
        <span className="font-display text-[17px] font-bold tracking-tight text-white">
          StrmAction
        </span>
      )}
    </span>
  )
}

export function TopBar() {
  const scrolled = useScrollDirection()
  const home = useHome()
  const navigate = useNavigate()
  const logout = useLogout()
  const auth = useAuthState()
  const needsAttention = home.data?.needs_attention ?? 0

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-all duration-500 ${
        scrolled ? 'glass border-b border-white/8' : 'bg-gradient-to-b from-black/55 to-transparent'
      }`}
    >
      <div className="mx-auto flex h-[68px] max-w-[1680px] items-center gap-4 px-4 sm:px-8 lg:px-12">
        <NavLink to="/" className="focus-ring shrink-0 rounded-xl" aria-label="StrmAction 首页">
          <Logo />
        </NavLink>

        <nav className="ml-4 hidden items-center gap-1 md:flex">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                `focus-ring relative rounded-full px-4 py-2 text-[14px] transition ${
                  isActive ? 'text-white' : 'text-ink-300 hover:text-white'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <span className="relative z-10">{link.label}</span>
                  {isActive ? (
                    <motion.span
                      layoutId="nav-pill"
                      className="absolute inset-0 rounded-full bg-white/10"
                      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                    />
                  ) : null}
                </>
              )}
            </NavLink>
          ))}
          {needsAttention > 0 ? (
            <NavLink
              to="/fix"
              className="focus-ring ml-2 flex items-center gap-1.5 rounded-full border border-amber-400/25 bg-amber-400/10 px-3 py-1.5 text-xs font-medium text-amber-300 transition hover:bg-amber-400/15"
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              {t('nav.needsAttention', { count: needsAttention })}
            </NavLink>
          ) : null}
        </nav>

        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => navigate('/search')}
            className="btn-icon md:hidden"
            aria-label={t('nav.search')}
          >
            <Search className="h-[18px] w-[18px]" />
          </button>
          <NavLink to="/search" className="btn-icon hidden md:grid" aria-label={t('nav.search')}>
            <Search className="h-[18px] w-[18px]" />
          </NavLink>
          <NavLink to="/settings" className="btn-icon md:hidden" aria-label={t('nav.settings')}>
            <Settings className="h-[18px] w-[18px]" />
          </NavLink>
          <button
            type="button"
            onClick={() => logout.mutate()}
            className="btn-icon"
            aria-label={t('nav.logout')}
            title={auth.data?.username ? `${auth.data.username} · ${t('nav.logout')}` : t('nav.logout')}
          >
            <LogOut className="h-[18px] w-[18px]" />
          </button>
        </div>
      </div>
    </header>
  )
}

const mobileLinks = [
  { to: '/', label: t('nav.home'), end: true, icon: Clapperboard },
  { to: '/search', label: t('nav.search'), icon: Search },
  { to: '/tasks', label: t('nav.tasks'), icon: AlertTriangle },
  { to: '/settings', label: t('nav.settings'), icon: Settings },
]

export function BottomNav() {
  return (
    <nav className="safe-bottom fixed inset-x-0 bottom-0 z-50 border-t border-white/8 bg-[#0a0c11]/95 backdrop-blur-xl md:hidden">
      <div className="mx-auto flex max-w-lg items-stretch justify-around px-2 py-1.5">
        {mobileLinks.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            className={({ isActive }) =>
              `flex min-w-[64px] flex-col items-center gap-1 rounded-xl px-3 py-2 text-[10px] transition ${
                isActive ? 'text-accent' : 'text-ink-400'
              }`
            }
          >
            <link.icon className="h-5 w-5" strokeWidth={1.7} />
            <span>{link.label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
