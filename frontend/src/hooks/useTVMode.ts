import { useEffect, useRef, useState } from 'react'
import { useUIStore } from '../store/ui'

function detectTV(): boolean {
  const params = new URLSearchParams(window.location.search)
  if (params.get('tv') === '1') return true
  // 伴侣 App 电视端由原生层追加 ?tv=1；手机端不追加，避免误进 10-foot 布局
  const bridge = typeof window !== 'undefined' ? window.StrmActionNative : undefined
  if (bridge?.isTV?.()) return true
  const coarse = window.matchMedia('(hover: none)').matches
  const touch = 'ontouchstart' in window || navigator.maxTouchPoints > 0
  return window.innerWidth >= 1920 && coarse && !touch
}

export function useTVMode() {
  const tvMode = useUIStore((state) => state.tvMode)
  const setTvMode = useUIStore((state) => state.setTvMode)
  const initialized = useRef(false)

  useEffect(() => {
    if (initialized.current) {
      document.documentElement.dataset.tv = String(tvMode)
      return
    }
    initialized.current = true
    const detected = detectTV()
    setTvMode(detected)
    document.documentElement.dataset.tv = String(detected)
  }, [setTvMode, tvMode])

  return tvMode
}

function focusableElements(): HTMLElement[] {
  const selector =
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  return Array.from(document.querySelectorAll<HTMLElement>(selector)).filter((el) => {
    if (el.offsetParent === null) return false
    const rect = el.getBoundingClientRect()
    return rect.width > 2 && rect.height > 2
  })
}

function center(rect: DOMRect) {
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
}

export function useSpatialNavigation(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (event: KeyboardEvent) => {
      const keys = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']
      if (!keys.includes(event.key)) return
      const active = document.activeElement as HTMLElement | null
      // 输入框里左右键是光标移动，不能被焦点导航抢走
      const tag = active?.tagName
      if (
        (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') &&
        (event.key === 'ArrowLeft' || event.key === 'ArrowRight')
      ) {
        return
      }
      const candidates = focusableElements()
      if (!candidates.length) return
      if (!active || !candidates.includes(active)) {
        event.preventDefault()
        candidates[0]?.focus()
        return
      }
      const current = center(active.getBoundingClientRect())
      const directional = candidates.filter((el) => el !== active)
      let best: { el: HTMLElement; score: number } | null = null
      for (const el of directional) {
        const point = center(el.getBoundingClientRect())
        const dx = point.x - current.x
        const dy = point.y - current.y
        let primary = 0
        let secondary = 0
        if (event.key === 'ArrowRight') {
          if (dx <= 8) continue
          primary = dx
          secondary = Math.abs(dy)
        } else if (event.key === 'ArrowLeft') {
          if (dx >= -8) continue
          primary = -dx
          secondary = Math.abs(dy)
        } else if (event.key === 'ArrowDown') {
          if (dy <= 8) continue
          primary = dy
          secondary = Math.abs(dx)
        } else {
          if (dy >= -8) continue
          primary = -dy
          secondary = Math.abs(dx)
        }
        const score = primary + secondary * 2.4
        if (!best || score < best.score) best = { el, score }
      }
      if (best) {
        event.preventDefault()
        best.el.focus({ preventScroll: true })
        best.el.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        // 该方向已经没有被聚焦元素：整页滚动，保证遥控器永远能「滑」下去
        event.preventDefault()
        const amount = Math.round(window.innerHeight * 0.62)
        window.scrollBy({
          top: event.key === 'ArrowDown' ? amount : -amount,
          behavior: 'smooth',
        })
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled])
}

export function useScrollDirection() {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  return scrolled
}
