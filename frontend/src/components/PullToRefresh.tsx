import { useEffect, useRef, useState, type ReactNode } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { RefreshCw } from 'lucide-react'
import { t } from '../i18n/zh-CN'

interface PullToRefreshProps {
  onRefresh: () => Promise<void> | void
  isRefreshing: boolean
  disabled?: boolean
  children: ReactNode
}

const THRESHOLD = 56
const MAX_PULL = 84

export function PullToRefresh({
  onRefresh,
  isRefreshing,
  disabled = false,
  children,
}: PullToRefreshProps) {
  const [pullDistance, setPullDistance] = useState(0)
  const startYRef = useRef(0)
  const startXRef = useRef(0)
  const isEligibleRef = useRef(false)
  const isPullingRef = useRef(false)

  useEffect(() => {
    if (disabled) return

    const handleTouchStart = (e: TouchEvent) => {
      // 只有在页面处于最顶部时才允许触发下拉刷新
      if (window.scrollY > 0 || isRefreshing) {
        isEligibleRef.current = false
        return
      }
      const touch = e.touches[0]
      startYRef.current = touch.clientY
      startXRef.current = touch.clientX
      isEligibleRef.current = true
      isPullingRef.current = false
    }

    const handleTouchMove = (e: TouchEvent) => {
      if (!isEligibleRef.current || isRefreshing) return

      const touch = e.touches[0]
      const deltaY = touch.clientY - startYRef.current
      const deltaX = touch.clientX - startXRef.current

      // 如果水平滑动距离大于垂直滑动距离，判定为水平滑动（如划动海报行），不触发下拉
      if (!isPullingRef.current && Math.abs(deltaX) > Math.abs(deltaY)) {
        isEligibleRef.current = false
        return
      }

      // 如果在滑动过程中页面向下滚动了，取消下拉
      if (window.scrollY > 0) {
        isEligibleRef.current = false
        setPullDistance(0)
        return
      }

      if (deltaY > 0) {
        isPullingRef.current = true
        // 阻尼公式：拉得越长阻力越大
        const damped = Math.min(Math.pow(deltaY, 0.8) * 1.6, MAX_PULL)
        setPullDistance(damped)

        // 当已经处于下拉状态且在顶部时，阻止浏览器默认的过度拉伸动作
        if (e.cancelable && damped > 8) {
          e.preventDefault()
        }
      } else {
        setPullDistance(0)
      }
    }

    const handleTouchEnd = () => {
      if (!isEligibleRef.current) return
      isEligibleRef.current = false

      if (pullDistance >= THRESHOLD && !isRefreshing) {
        void onRefresh()
      }
      setPullDistance(0)
      isPullingRef.current = false
    }

    window.addEventListener('touchstart', handleTouchStart, { passive: true })
    window.addEventListener('touchmove', handleTouchMove, { passive: false })
    window.addEventListener('touchend', handleTouchEnd, { passive: true })
    window.addEventListener('touchcancel', handleTouchEnd, { passive: true })

    return () => {
      window.removeEventListener('touchstart', handleTouchStart)
      window.removeEventListener('touchmove', handleTouchMove)
      window.removeEventListener('touchend', handleTouchEnd)
      window.removeEventListener('touchcancel', handleTouchEnd)
    }
  }, [disabled, isRefreshing, onRefresh, pullDistance])

  const showIndicator = pullDistance > 0 || isRefreshing
  const isReady = pullDistance >= THRESHOLD

  return (
    <>
      <AnimatePresence>
        {showIndicator ? (
          <motion.div
            key="pull-indicator"
            initial={{ opacity: 0, y: -24, scale: 0.9 }}
            animate={{
              opacity: 1,
              y: isRefreshing ? 12 : Math.min(pullDistance * 0.45, 24),
              scale: 1,
            }}
            exit={{ opacity: 0, y: -24, scale: 0.9 }}
            transition={{ type: 'spring', damping: 25, stiffness: 350 }}
            className="pointer-events-none fixed left-1/2 top-[72px] z-40 -translate-x-1/2"
          >
            <div className="flex items-center gap-2 rounded-full border border-white/12 bg-[#121620]/95 px-4 py-2 text-[12px] font-medium text-white shadow-[0_12px_32px_rgba(0,0,0,0.55)] backdrop-blur-xl">
              <RefreshCw
                className={`h-3.5 w-3.5 transition-colors ${
                  isRefreshing
                    ? 'animate-spin text-accent'
                    : isReady
                      ? 'text-accent'
                      : 'text-ink-400'
                }`}
                style={{
                  transform: isRefreshing ? undefined : `rotate(${pullDistance * 5}deg)`,
                }}
              />
              <span className="text-ink-200">
                {isRefreshing
                  ? t('pullToRefresh.refreshing')
                  : isReady
                    ? t('pullToRefresh.release')
                    : t('pullToRefresh.pull')}
              </span>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
      {children}
    </>
  )
}
