import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Play, X } from 'lucide-react'
import { useStartPlayback } from '../hooks/useStartPlayback'
import { t } from '../i18n/zh-CN'

interface NextEvent {
  id: number
  label: string
}

export function AutoNextOverlay() {
  const start = useStartPlayback()
  const [next, setNext] = useState<NextEvent | null>(null)
  const [remaining, setRemaining] = useState(5)
  const nextRef = useRef<NextEvent | null>(null)
  const startRef = useRef(start)
  startRef.current = start

  useEffect(() => {
    const onNext = (event: Event) => {
      const detail = (event as CustomEvent<NextEvent>).detail
      if (!detail?.id) return
      nextRef.current = detail
      setNext(detail)
      setRemaining(5)
    }
    window.addEventListener('strmaction:next', onNext)
    return () => window.removeEventListener('strmaction:next', onNext)
  }, [])

  useEffect(() => {
    if (!next) return
    if (remaining <= 0) {
      const target = nextRef.current
      nextRef.current = null
      setNext(null)
      if (target) void startRef.current(target.id)
      return
    }
    const timer = window.setTimeout(() => setRemaining((value) => value - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [next, remaining])

  const cancel = () => {
    nextRef.current = null
    setNext(null)
  }

  return (
    <AnimatePresence>
      {next ? (
        <motion.div
          initial={{ opacity: 0, y: 30, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 20, scale: 0.97 }}
          transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
          className="fixed bottom-20 left-1/2 z-[80] w-[min(92vw,420px)] -translate-x-1/2 md:bottom-8"
        >
          <div className="flex items-center gap-3 rounded-2xl border border-white/12 bg-[#0e1219]/96 p-3.5 shadow-lift backdrop-blur-xl">
            <div className="relative grid h-12 w-12 shrink-0 place-items-center">
              <svg viewBox="0 0 48 48" className="absolute inset-0 h-12 w-12 -rotate-90">
                <circle cx="24" cy="24" r="20" fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="3" />
                <circle
                  cx="24"
                  cy="24"
                  r="20"
                  fill="none"
                  stroke="var(--accent, #e8b06a)"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeDasharray={2 * Math.PI * 20}
                  strokeDashoffset={2 * Math.PI * 20 * (1 - remaining / 5)}
                  style={{ transition: 'stroke-dashoffset 1s linear' }}
                />
              </svg>
              <span className="text-[13px] font-bold text-white">{remaining}</span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-accent/85">
                <Play className="h-3 w-3 fill-current" />
                {t('player.autoPlayNext')}
              </p>
              <p className="mt-0.5 line-clamp-1 text-[13px] font-medium text-white">
                {t('player.nextEpisode')}
                {next.label ? <span className="ml-1.5 text-ink-300">{next.label}</span> : null}
              </p>
              <p className="mt-0.5 text-[10.5px] text-ink-500">{t('player.nextEpisodeHint')}</p>
            </div>
            <button
              type="button"
              onClick={cancel}
              className="btn-icon shrink-0"
              aria-label={t('common.cancel')}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}
