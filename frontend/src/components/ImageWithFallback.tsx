import { useState } from 'react'
import { Film } from 'lucide-react'

interface Props {
  src: string | null | undefined
  alt: string
  className?: string
  color?: string | null
  imgClassName?: string
  children?: React.ReactNode
  eager?: boolean
}

export function ImageWithFallback({
  src,
  alt,
  className = '',
  color,
  imgClassName = '',
  children,
  eager = false,
}: Props) {
  const [failed, setFailed] = useState(false)
  const showImage = Boolean(src) && !failed
  const accent = color || '#2b3242'
  return (
    <div className={`relative overflow-hidden bg-ink-850 ${className}`}>
      {showImage ? (
        <img
          src={src as string}
          alt={alt}
          loading={eager ? 'eager' : 'lazy'}
          decoding="async"
          draggable={false}
          onError={() => setFailed(true)}
          className={`h-full w-full object-cover ${imgClassName}`}
        />
      ) : (
        <div
          className="flex h-full w-full items-center justify-center"
          style={{
            background: `radial-gradient(120% 120% at 20% 0%, ${accent}55 0%, #0b0d11 65%), linear-gradient(160deg, #131826, #07080a)`,
          }}
        >
          <div className="flex flex-col items-center gap-2 px-3 text-center text-white/45">
            <Film className="h-7 w-7" strokeWidth={1.4} />
            <span className="line-clamp-2 text-[11px] font-medium leading-tight">{alt}</span>
          </div>
        </div>
      )}
      {children}
    </div>
  )
}
