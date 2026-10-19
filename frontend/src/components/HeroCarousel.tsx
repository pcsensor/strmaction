import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Info, Play, Star } from 'lucide-react'
import type { HeroItem } from '../api/types'
import { ImageWithFallback } from './ImageWithFallback'
import { useStartPlayback } from '../hooks/useStartPlayback'
import { useUIStore } from '../store/ui'
import { t } from '../i18n/zh-CN'

interface Props {
  items: HeroItem[]
  interval?: number
}

export function HeroCarousel({ items, interval = 8000 }: Props) {
  const [active, setActive] = useState(0)
  const [paused, setPaused] = useState(false)
  const start = useStartPlayback()
  const tvMode = useUIStore((state) => state.tvMode)
  const touchStart = useRef<{ x: number; y: number; at: number } | null>(null)

  const current = items[active]
  const total = items.length

  const rotate = useCallback(() => {
    setActive((index) => (index + 1) % Math.max(1, total))
  }, [total])

  const step = useCallback(
    (delta: number) => {
      setActive((index) => (index + delta + Math.max(1, total)) % Math.max(1, total))
    },
    [total],
  )

  // 手机：横向滑动切换轮播；纵向手势不拦截，交给页面滚动
  const onTouchStart = useCallback((event: React.TouchEvent) => {
    const point = event.touches[0]
    if (!point) return
    touchStart.current = { x: point.clientX, y: point.clientY, at: Date.now() }
    setPaused(true)
  }, [])

  const onTouchEnd = useCallback(
    (event: React.TouchEvent) => {
      setPaused(false)
      const origin = touchStart.current
      touchStart.current = null
      if (!origin) return
      const point = event.changedTouches[0]
      if (!point) return
      const dx = point.clientX - origin.x
      const dy = point.clientY - origin.y
      // 只认「明显横向」且足够快的手势，避免和纵向滚动打架
      if (Math.abs(dx) < 44 || Math.abs(dx) < Math.abs(dy) * 1.25) return
      if (Date.now() - origin.at > 900) return
      step(dx < 0 ? 1 : -1)
    },
    [step],
  )

  useEffect(() => {
    if (paused || total <= 1) return
    const timer = window.setInterval(rotate, Math.max(4000, interval))
    return () => window.clearInterval(timer)
  }, [interval, paused, rotate, total, active])

  const genres = useMemo(
    () => (current?.genres || []).filter(Boolean).slice(0, 3),
    [current],
  )

  if (!current) return null

  return (
    <section
      className="relative isolate min-h-[520px] w-full overflow-hidden sm:min-h-[680px]"
      style={{ touchAction: 'pan-y' }}
      onTouchStart={onTouchStart}
      onTouchEnd={onTouchEnd}
      onTouchCancel={() => {
        touchStart.current = null
        setPaused(false)
      }}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setPaused(false)
        }
      }}
      aria-roledescription="carousel"
      aria-label={t('home.featured')}
    >
      <AnimatePresence initial={false} mode="sync">
        <motion.div
          key={current.id}
          className="absolute inset-0 -z-10"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 1.1, ease: 'easeOut' }}
        >
          <div className="absolute inset-0 overflow-hidden">
            <ImageWithFallback
              src={current.backdrop_large || current.backdrop}
              alt={current.title}
              color={current.color}
              eager
              className="h-full w-full"
              imgClassName={`h-full w-full object-cover ${tvMode ? '' : 'kenburns'}`}
            />
          </div>
          <div className="absolute inset-0 bg-gradient-to-r from-[#07080a] via-[#07080a]/55 to-transparent" />
          <div className="absolute inset-0 bg-gradient-to-t from-[#07080a] via-transparent to-[#07080a]/40" />
        </motion.div>
      </AnimatePresence>

      <div className="relative mx-auto flex min-h-[520px] max-w-[1680px] items-end px-5 pb-14 pt-20 sm:min-h-[680px] sm:px-10 sm:pb-28 sm:pt-28 lg:px-16">
        <AnimatePresence mode="wait">
          <motion.div
            key={current.id}
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
            className="max-w-[680px]"
            style={{ ['--accent' as string]: current.color || '#e8b06a' }}
          >
            <div className="mb-4 flex items-center gap-2.5">
              <span className="rounded-full border border-accent/35 bg-accent/10 px-3 py-1 text-[10.5px] font-bold uppercase tracking-[0.16em] text-accent">
                {current.kind === 'movie' ? 'FEATURED FILM' : 'FEATURED SERIES'}
              </span>
              {current.certification ? (
                <span className="rounded border border-white/20 px-1.5 py-0.5 text-[10px] font-semibold text-white/70">
                  {current.certification}
                </span>
              ) : null}
            </div>

            {current.logo ? (
              <img
                src={current.logo}
                alt={current.title}
                className="mb-4 max-h-[120px] w-auto max-w-[80%] object-contain drop-shadow-[0_10px_30px_rgba(0,0,0,0.6)] sm:max-h-[150px]"
              />
            ) : (
              <h1 className="hero-title font-display text-[38px] font-black leading-[1.04] tracking-tight text-white drop-shadow-[0_14px_40px_rgba(0,0,0,0.65)] sm:text-6xl">
                {current.title}
              </h1>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px] text-ink-200">
              {current.year ? <span className="font-medium">{current.year}</span> : null}
              {current.rating ? (
                <span className="flex items-center gap-1 font-semibold text-amber-300">
                  <Star className="h-3.5 w-3.5 fill-current" />
                  {current.rating.toFixed(1)}
                </span>
              ) : null}
              {current.runtime_min ? (
                <span className="text-ink-300">
                  {current.runtime_min} {t('common.minutes')}
                </span>
              ) : null}
              {genres.map((genre, index) => (
                <span key={genre} className="flex items-center gap-3">
                  {index === 0 ? <span className="text-white/25">/</span> : null}
                  {genre}
                </span>
              ))}
            </div>

            <p className="mt-4 line-clamp-3 max-w-[560px] text-[14px] leading-relaxed text-ink-200/90 sm:text-[15px]">
              {current.tagline ? (
                <span className="font-medium text-accent/90">「{current.tagline}」</span>
              ) : null}
              {current.overview || t('detail.noOverview')}
            </p>

            <div className="mt-7 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => start(current.id)}
                className="btn-primary gap-2.5 px-7 py-3.5 text-[15px] shadow-[0_18px_50px_-16px_rgba(255,255,255,0.4)]"
              >
                <Play className="h-4.5 w-4.5 fill-current" />
                {t('common.play')}
              </button>
              <Link to={`/item/${current.id}`} className="btn-ghost gap-2 px-6 py-3.5">
                <Info className="h-4 w-4" />
                {t('common.detail')}
              </Link>
            </div>
          </motion.div>
        </AnimatePresence>
      </div>

      {total > 1 ? (
        <div className="absolute bottom-8 right-5 z-10 flex items-center gap-2 sm:right-10 lg:right-16">
          {items.map((item, index) => (
            <button
              key={item.id}
              type="button"
              aria-label={`切换到 ${item.title}`}
              aria-current={index === active}
              onClick={() => setActive(index)}
              className={`h-1.5 rounded-full transition-all duration-500 ${
                index === active
                  ? 'w-8 bg-white'
                  : 'w-4 bg-white/35 hover:bg-white/60'
              }`}
            />
          ))}
        </div>
      ) : null}
    </section>
  )
}
