import React from 'react'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import type { Film } from 'lucide-react'
import { t } from '../../i18n/zh-CN'

export function Section({
  id,
  title,
  description,
  icon: Icon,
  children,
}: {
  id: string
  title: string
  description?: string
  icon: typeof Film
  children: React.ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-28">
      <div className="mb-4 flex items-start gap-3">
        <div className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/5 text-accent">
          <Icon className="h-[17px] w-[17px]" />
        </div>
        <div>
          <h2 className="font-display text-lg font-semibold text-white">{title}</h2>
          {description ? <p className="mt-0.5 text-[12.5px] text-ink-400">{description}</p> : null}
        </div>
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint ? <p className="mt-1.5 text-[11px] leading-relaxed text-ink-500">{hint}</p> : null}
    </div>
  )
}

export function TestBadge({
  result,
}: {
  result?: { ok: boolean; message: string; latency: number }
}) {
  if (!result) return null
  return (
    <p
      className={`mt-3 flex items-center gap-1.5 text-[11.5px] ${
        result.ok ? 'text-emerald-300' : 'text-rose-300'
      }`}
    >
      {result.ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
      {result.ok
        ? t('settings.providers.testOk', { ms: result.latency })
        : t('settings.providers.testFailed', { message: result.message })}
    </p>
  )
}

export function headersToText(headers?: Record<string, string> | null): string {
  if (!headers) return ''
  return Object.entries(headers)
    .map(([key, value]) => `${key}: ${value}`)
    .join('\n')
}

export function textToHeaders(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const index = line.indexOf(':')
    if (index <= 0) continue
    const key = line.slice(0, index).trim()
    const value = line.slice(index + 1).trim()
    if (!key || !value) continue
    out[key] = value
  }
  return out
}
