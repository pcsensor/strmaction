import { useEffect, useState } from 'react'
import { Film, Folder } from 'lucide-react'

interface Props {
  src: string | null | undefined
  alt: string
  className?: string
  color?: string | null
  kind?: string
  imgClassName?: string
  children?: React.ReactNode
  eager?: boolean
}

export function ImageWithFallback({
  src,
  alt,
  className = '',
  color,
  kind,
  imgClassName = '',
  children,
  eager = false,
}: Props) {
  const [failed, setFailed] = useState(false)
  useEffect(() => setFailed(false), [src])
  const showImage = Boolean(src) && !failed
  const accent = color || (kind === 'folder' ? '#d97706' : '#2b3242')
  return (
    <div className={`relative h-full w-full overflow-hidden bg-ink-850 ${className}`}>
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
          className="flex h-full w-full flex-col items-center justify-center p-3 text-center"
          style={{
            background: `radial-gradient(120% 120% at 20% 0%, ${accent}55 0%, #0b0d11 65%), linear-gradient(160deg, #131826, #07080a)`,
          }}
        >
          <div className="flex flex-col items-center justify-center gap-2.5 px-2 text-center text-white/50">
            {kind === 'folder' ? (
              <Folder className="h-8 w-8 text-amber-400/85" strokeWidth={1.5} />
            ) : (
              <Film className="h-8 w-8 text-white/45" strokeWidth={1.4} />
            )}
            <span className="line-clamp-3 text-[11.5px] font-medium leading-tight text-ink-200">{alt}</span>
          </div>
        </div>
      )}
      {children}
    </div>
  )
}
