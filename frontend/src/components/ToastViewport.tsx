import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'
import { useUIStore, type Toast } from '../store/ui'

function ToastItem({ toast }: { toast: Toast }) {
  const dismiss = useUIStore((state) => state.dismissToast)
  useEffect(() => {
    const timer = window.setTimeout(() => dismiss(toast.id), toast.timeout ?? 3600)
    return () => window.clearTimeout(timer)
  }, [dismiss, toast.id, toast.timeout])

  const tone = toast.tone || 'default'
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'error' ? AlertCircle : Info

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 16, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 10, scale: 0.97 }}
      transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      className="pointer-events-auto flex w-full max-w-[420px] items-start gap-3 rounded-2xl border border-white/10 bg-[#111520]/95 p-4 shadow-lift backdrop-blur-xl"
    >
      <Icon
        className={`mt-0.5 h-5 w-5 shrink-0 ${
          tone === 'success'
            ? 'text-emerald-400'
            : tone === 'error'
              ? 'text-rose-400'
              : 'text-accent'
        }`}
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-white">{toast.title}</p>
        {toast.description ? (
          <p className="mt-1 break-words text-[13px] leading-relaxed text-ink-300">
            {toast.description}
          </p>
        ) : null}
        {toast.actionLabel && toast.onAction ? (
          <button
            type="button"
            onClick={() => {
              toast.onAction?.()
              dismiss(toast.id)
            }}
            className="mt-2.5 rounded-full border border-accent/40 bg-accent/10 px-3 py-1 text-xs font-medium text-accent transition hover:bg-accent/20"
          >
            {toast.actionLabel}
          </button>
        ) : null}
      </div>
      <button
        type="button"
        aria-label="关闭"
        onClick={() => dismiss(toast.id)}
        className="rounded-full p-1 text-ink-400 transition hover:bg-white/10 hover:text-white"
      >
        <X className="h-4 w-4" />
      </button>
    </motion.div>
  )
}

export function ToastViewport() {
  const toasts = useUIStore((state) => state.toasts)
  const tvMode = useUIStore((state) => state.tvMode)
  return (
    <div
      className={`pointer-events-none fixed inset-x-0 z-[100] flex flex-col items-center gap-2 px-4 ${
        tvMode ? 'bottom-16' : 'bottom-6'
      }`}
    >
      <AnimatePresence initial={false}>
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} />
        ))}
      </AnimatePresence>
    </div>
  )
}
