import { Component, useEffect, useRef, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { api } from './api/client'
import { useAuthState, useTaskUpdates } from './api/hooks'
import { TopBar, BottomNav, Logo } from './components/TopBar'
import { ToastViewport } from './components/ToastViewport'
import { AutoNextOverlay } from './components/AutoNextOverlay'
import type { ItemDetailResponse } from './api/types'
import { useSpatialNavigation, useTVMode } from './hooks/useTVMode'
import { useStartPlayback } from './hooks/useStartPlayback'
import { useAppRefresh } from './hooks/useAppRefresh'
import { PullToRefresh } from './components/PullToRefresh'
import { useUIStore } from './store/ui'
import { HomePage } from './pages/HomePage'
import { LibrariesPage } from './pages/LibrariesPage'
import { DetailPage } from './pages/DetailPage'
import { SearchPage } from './pages/SearchPage'
import { SettingsPage } from './pages/SettingsPage'
import { TasksPage } from './pages/TasksPage'
import { FixPage } from './pages/FixPage'
import { LoginPage } from './pages/LoginPage'
import { SetupPage } from './pages/SetupPage'
import { UsersPage } from './pages/UsersPage'
import { EmptyState } from './components/EmptyState'
import { t } from './i18n/zh-CN'

const ONBOARDING_KEY = 'strmaction:onboarding'

function ScrollToTop() {
  const location = useLocation()
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior })
  }, [location.pathname, location.search])
  return null
}

function AppShell({ children }: { children: ReactNode }) {
  useTaskUpdates()
  const tvMode = useUIStore((state) => state.tvMode)
  useSpatialNavigation(tvMode)
  const { refresh, isRefreshing } = useAppRefresh()

  return (
    <div className={`min-h-screen ${tvMode ? 'tv-overscan' : ''}`}>
      <TopBar onRefresh={() => void refresh({ showToast: true })} isRefreshing={isRefreshing} />
      <ScrollToTop />
      <PullToRefresh
        onRefresh={() => refresh({ showToast: true })}
        isRefreshing={isRefreshing}
        disabled={tvMode}
      >
        <main className="pb-8">{children}</main>
      </PullToRefresh>
      <footer className="mx-auto mt-8 max-w-[1680px] border-t border-white/6 px-5 pb-24 pt-6 text-center text-[10px] leading-relaxed text-ink-500 sm:px-10 md:pb-8 lg:px-16">
        {t('app.footer')}
      </footer>
      <BottomNav />
      <AutoNextOverlay />
      {tvMode ? (
        <div className="pointer-events-none fixed bottom-4 left-1/2 z-40 -translate-x-1/2 rounded-full border border-white/10 bg-black/55 px-4 py-1.5 text-[10px] text-white/45 backdrop-blur">
          {t('tv.hint')}
        </div>
      ) : null}
      <ToastViewport />
    </div>
  )
}

function NotFound() {
  return (
    <div className="mx-auto max-w-2xl px-5 pt-32">
      <EmptyState
        icon={AlertTriangle}
        title={t('common.notFound')}
        description="这个地址没有对应的页面。"
        action={
          <a href="/" className="btn-primary">
            {t('common.backHome')}
          </a>
        }
      />
    </div>
  )
}

function Splash() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6">
      <Logo />
      <Loader2 className="h-5 w-5 animate-spin text-accent" />
      <p className="text-[11px] tracking-[0.2em] text-ink-500">LOADING LIBRARY</p>
    </div>
  )
}

function AdminRoute({ children }: { children: ReactNode }) {
  const auth = useAuthState()
  if (auth.data?.user?.role !== 'admin') {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-2xl px-5 pt-32">
          <EmptyState
            icon={AlertTriangle}
            title="页面出错了"
            description={this.state.error.message}
            action={
              <button type="button" onClick={() => window.location.reload()} className="btn-primary">
                刷新页面
              </button>
            }
          />
        </div>
      )
    }
    return this.props.children
  }
}

export default function App() {
  const auth = useAuthState()
  const queryClient = useQueryClient()
  const startPlayback = useStartPlayback()
  const startPlaybackRef = useRef(startPlayback)
  startPlaybackRef.current = startPlayback
  useTVMode()

  // 桌面端内嵌播放器的“上一集/下一集/选集/自动连播”通过该事件请求网页发起播放。
  useEffect(() => {
    const onRequestPlay = (event: Event) => {
      const detail = (event as CustomEvent<{ itemId?: number }>).detail
      const itemId = Number(detail?.itemId)
      if (!Number.isFinite(itemId) || itemId <= 0) return
      void startPlaybackRef.current(itemId)
    }
    window.addEventListener('strmaction:request-play', onRequestPlay)
    return () => window.removeEventListener('strmaction:request-play', onRequestPlay)
  }, [])

  useEffect(() => {
    const onUnauthorized = () => {
      queryClient.invalidateQueries({ queryKey: ['auth'] })
    }
    window.addEventListener('strmaction:unauthorized', onUnauthorized)
    return () => window.removeEventListener('strmaction:unauthorized', onUnauthorized)
  }, [queryClient])

  useEffect(() => {
    window.StrmActionReport = (itemId, positionMs, durationMs, finished) => {
      void api
        .post(`/api/items/${itemId}/progress`, {
          position_ms: positionMs,
          duration_ms: durationMs > 0 ? durationMs : undefined,
          finished,
        })
        .catch(() => undefined)
        .finally(() => {
          window.dispatchEvent(new CustomEvent('strmaction:progress-updated'))
        })
    }
    const onProgress = () => {
      queryClient.invalidateQueries({ queryKey: ['home'] })
      queryClient.invalidateQueries({ queryKey: ['item'] })
    }
    window.StrmActionNextEpisode = (itemId, finished) => {
      if (!finished) return
      void api
        .get<ItemDetailResponse>(`/api/items/${itemId}`)
        .then((detail) => {
          const nextId = detail.next_episode_id
          if (!nextId) return
          const episodes = detail.seasons.flatMap((season) => season.episodes)
          const next = episodes.find((episode) => episode.id === nextId)
          window.dispatchEvent(
            new CustomEvent('strmaction:next', {
              detail: {
                id: nextId,
                label: next?.episode_code || next?.title || '',
              },
            }),
          )
        })
        .catch(() => undefined)
    }
    window.addEventListener('strmaction:progress-updated', onProgress)
    return () => {
      window.removeEventListener('strmaction:progress-updated', onProgress)
      delete window.StrmActionReport
      delete window.StrmActionNextEpisode
    }
  }, [queryClient])

  if (auth.isLoading) return <Splash />

  const needsSetup = auth.data?.needs_setup ?? false
  const authenticated = auth.data?.authenticated ?? false
  const onboarding =
    typeof window !== 'undefined' && sessionStorage.getItem(ONBOARDING_KEY) === '1'

  if (needsSetup || (authenticated && onboarding)) {
    return (
      <ErrorBoundary>
        <SetupPage />
        <ToastViewport />
      </ErrorBoundary>
    )
  }

  if (!authenticated) {
    return (
      <ErrorBoundary>
        <LoginPage />
        <ToastViewport />
      </ErrorBoundary>
    )
  }

  return (
    <ErrorBoundary>
      <AppShell>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/libraries" element={<LibrariesPage />} />
          <Route path="/libraries/:id" element={<LibrariesPage />} />
          <Route path="/item/:id" element={<DetailPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route
            path="/users"
            element={
              <AdminRoute>
                <UsersPage />
              </AdminRoute>
            }
          />
          <Route
            path="/tasks"
            element={
              <AdminRoute>
                <TasksPage />
              </AdminRoute>
            }
          />
          <Route path="/settings" element={<SettingsPage />} />
          <Route
            path="/fix"
            element={
              <AdminRoute>
                <FixPage />
              </AdminRoute>
            }
          />
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AppShell>
    </ErrorBoundary>
  )
}
