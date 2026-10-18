import { useEffect, useState } from 'react'
import type { ItemDetail } from '../api/types'
import { usePatchItem } from '../api/hooks'
import { Modal } from './Modal'
import { useToast } from '../store/ui'
import { t } from '../i18n/zh-CN'

interface Props {
  open: boolean
  item: ItemDetail | null
  onClose: () => void
}

export function EditDialog({ open, item, onClose }: Props) {
  const patch = usePatchItem()
  const toast = useToast()
  const [form, setForm] = useState({
    title: '',
    original_title: '',
    year: '',
    overview: '',
    tagline: '',
    certification: '',
  })
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open && item) {
      setForm({
        title: item.title || '',
        original_title: item.original_title || '',
        year: item.year ? String(item.year) : '',
        overview: item.overview || '',
        tagline: item.tagline || '',
        certification: item.certification || '',
      })
      setError(null)
    }
  }, [item, open])

  const update = (key: keyof typeof form, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const save = async () => {
    if (!item) return
    if (!form.title.trim()) {
      setError(t('common.required') + '：' + t('detail.edit.title'))
      return
    }
    const body: Record<string, unknown> = {
      title: form.title.trim(),
      original_title: form.original_title.trim() || null,
      overview: form.overview.trim() || null,
      tagline: form.tagline.trim() || null,
      certification: form.certification.trim() || null,
    }
    if (form.year.trim()) {
      const year = Number(form.year)
      if (!Number.isFinite(year) || year < 1880 || year > 2200) {
        setError('年份格式不正确')
        return
      }
      body.year = Math.round(year)
    }
    try {
      await patch.mutateAsync({ id: item.id, body })
      toast({ title: t('toast.saved'), tone: 'success' })
      onClose()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('detail.editFields')}
      description={t('detail.edit.lockHint')}
      width="lg"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-ghost">
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={save}
            disabled={patch.isPending}
            className="btn-primary px-6 py-2.5 disabled:opacity-60"
          >
            {patch.isPending ? t('common.saving') : t('common.save')}
          </button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label className="label">{t('detail.edit.title')}</label>
          <input
            className="input"
            value={form.title}
            onChange={(event) => update('title', event.target.value)}
          />
        </div>
        <div>
          <label className="label">{t('detail.edit.originalTitle')}</label>
          <input
            className="input"
            value={form.original_title}
            onChange={(event) => update('original_title', event.target.value)}
          />
        </div>
        <div>
          <label className="label">{t('detail.edit.year')}</label>
          <input
            className="input"
            inputMode="numeric"
            value={form.year}
            onChange={(event) => update('year', event.target.value)}
          />
        </div>
        <div className="sm:col-span-2">
          <label className="label">{t('detail.edit.tagline')}</label>
          <input
            className="input"
            value={form.tagline}
            onChange={(event) => update('tagline', event.target.value)}
          />
        </div>
        <div className="sm:col-span-2">
          <label className="label">{t('detail.edit.overview')}</label>
          <textarea
            className="input min-h-[140px] resize-y leading-relaxed"
            value={form.overview}
            onChange={(event) => update('overview', event.target.value)}
          />
        </div>
        <div>
          <label className="label">{t('detail.edit.certification')}</label>
          <input
            className="input"
            value={form.certification}
            onChange={(event) => update('certification', event.target.value)}
          />
        </div>
      </div>
      {error ? (
        <p className="mt-4 rounded-xl border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </p>
      ) : null}
    </Modal>
  )
}
