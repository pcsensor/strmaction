import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { ItemSummary } from '../api/types'
import { PosterCard } from './PosterCard'
import { t } from '../i18n/zh-CN'

interface RowProps {
  title: string
  items: ItemSummary[]
  viewAllHref?: string
  eyebrow?: string
  children?: React.ReactNode
}

export function PosterRow({ title, items, viewAllHref, eyebrow, children }: RowProps) {
  const scroller = useRef<HTMLDivElement | null>(null)
  const [canLeft, setCanLeft] = useState(false)
  const [canRight, setCanRight] = useState(false)

  const update = useCallback(() => {
    const el = scroller.current
    if (!el) return
    setCanLeft(el.scrollLeft > 8)
    setCanRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 8)
  }, [])

  useEffect(() => {
    update()
    const el = scroller.current
    if (!el) return
    el.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      el.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [update, items.length])

  const scrollBy = (direction: number) => {
    const el = scroller.current
    if (!el) return
    el.scrollBy({ left: direction * el.clientWidth * 0.82, behavior: 'smooth' })
  }

  if (!items.length && !children) return null

  return (
    <section className="group/row relative">
      <div className="mb-4 flex items-end justify-between gap-4 px-1">
        <div>
          {eyebrow ? (
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-accent/80">
              {eyebrow}
            </p>
          ) : null}
          <h2 className="section-title">{title}</h2>
        </div>
        <div className="flex items-center gap-2">
          {viewAllHref ? (
            <Link
              to={viewAllHref}
              className="text-[12.5px] text-ink-400 transition hover:text-white"
            >
              {t('common.viewAll')}
            </Link>
          ) : null}
          <div className="hidden items-center gap-1.5 opacity-0 transition-opacity duration-300 group-hover/row:opacity-100 lg:flex">
            <button
              type="button"
              aria-label="向左滚动"
              disabled={!canLeft}
              onClick={() => scrollBy(-1)}
              className="btn-icon disabled:opacity-30"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label="向右滚动"
              disabled={!canRight}
              onClick={() => scrollBy(1)}
              className="btn-icon disabled:opacity-30"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      <div
        ref={scroller}
        className="no-scrollbar row-scroller flex gap-3.5 overflow-x-auto pb-2 sm:gap-4"
      >
        {children}
        {items.map((item) => (
          <PosterCard key={item.id} item={item} />
        ))}
      </div>
    </section>
  )
}
