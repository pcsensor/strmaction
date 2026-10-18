interface ProgressBarProps {
  value: number | null | undefined
  className?: string
  trackClassName?: string
  barClassName?: string
  thin?: boolean
}

export function ProgressBar({
  value,
  className = '',
  trackClassName = 'bg-white/15',
  barClassName = 'bg-accent',
  thin = false,
}: ProgressBarProps) {
  const percent = Math.min(100, Math.max(0, (value || 0) * 100))
  return (
    <div
      className={`w-full overflow-hidden rounded-full ${trackClassName} ${thin ? 'h-[3px]' : 'h-1.5'} ${className}`}
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={`h-full rounded-full transition-[width] duration-500 ${barClassName}`}
        style={{ width: `${percent}%` }}
      />
    </div>
  )
}
