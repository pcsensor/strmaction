import { Loader2 } from 'lucide-react'

export function Spinner({ className = 'h-5 w-5' }: { className?: string }) {
  return <Loader2 className={`animate-spin ${className}`} />
}

export function LoadingBlock({ label = '加载中…' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-ink-400">
      <Spinner className="h-6 w-6 text-accent" />
      <span className="text-sm">{label}</span>
    </div>
  )
}
