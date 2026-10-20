import { useEffect, useRef, useState } from 'react'
import { Database, Download, ScanLine, Upload } from 'lucide-react'
import type { AppSettings } from '../../api/types'
import { useExportData, useImportData, usePatchSettings } from '../../api/hooks'
import { Spinner } from '../Spinner'
import { useToast } from '../../store/ui'
import { cnDate } from '../../utils/format'
import { t } from '../../i18n/zh-CN'
import { Section, Field } from './common'

export function SystemSettingsSection({ settings }: { settings: AppSettings }) {
  const patchSettings = usePatchSettings()
  const exportData = useExportData()
  const importData = useImportData()
  const toast = useToast()

  const [ignore, setIgnore] = useState('')
  const [followSymlinks, setFollowSymlinks] = useState(false)
  const [maxDepth, setMaxDepth] = useState('6')
  const fileInput = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!settings) return
    setIgnore((settings.scanner.ignore || []).join('\n'))
    setFollowSymlinks(Boolean(settings.scanner.follow_symlinks))
    setMaxDepth(String(settings.scanner.max_depth ?? 6))
  }, [settings])

  const save = async (patch: Record<string, unknown>, successTitle = t('settings.saved')) => {
    try {
      await patchSettings.mutateAsync(patch)
      toast({ title: successTitle, tone: 'success' })
      return true
    } catch (error) {
      toast({ title: t('settings.saveFailed'), description: (error as Error).message, tone: 'error' })
      return false
    }
  }

  const doExport = async () => {
    try {
      const data = await exportData.mutateAsync()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = t('settings.data.backupName', { date: cnDate() })
      anchor.click()
      URL.revokeObjectURL(url)
      toast({ title: '备份已导出', tone: 'success' })
    } catch (error) {
      toast({ title: t('common.failed'), description: (error as Error).message, tone: 'error' })
    }
  }

  const doImport = async (file: File | undefined) => {
    if (!file) return
    try {
      const text = await file.text()
      const data = JSON.parse(text) as Record<string, unknown>
      const result = await importData.mutateAsync(data)
      const imported = result.imported || {}
      toast({
        title: t('settings.data.imported', {
          libraries: Number(imported.libraries || 0),
          items: Number(imported.items || 0),
          progress: Number(imported.progress || 0),
        }),
        description: '建议重新扫描目录以恢复文件关联',
        tone: 'success',
        timeout: 7000,
      })
    } catch (error) {
      toast({ title: '导入失败', description: (error as Error).message, tone: 'error' })
    } finally {
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <>
      <Section id="scanner" title={t('settings.sections.scanner')} icon={ScanLine}>
        <div className="card p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('settings.scanner.ignore')}>
              <textarea
                className="input min-h-[100px] font-mono text-[12px]"
                value={ignore}
                onChange={(event) => setIgnore(event.target.value)}
              />
            </Field>
            <div className="space-y-4">
              <Field label={t('settings.scanner.maxDepth')}>
                <input
                  className="input"
                  inputMode="numeric"
                  value={maxDepth}
                  onChange={(event) => setMaxDepth(event.target.value)}
                />
              </Field>
              <label className="flex items-center gap-2.5 text-[12.5px] text-ink-200">
                <input
                  type="checkbox"
                  checked={followSymlinks}
                  onChange={(event) => setFollowSymlinks(event.target.checked)}
                  className="h-4 w-4 accent-[#e8b06a]"
                />
                {t('settings.scanner.followSymlinks')}
              </label>
            </div>
          </div>
          <div className="mt-5">
            <button
              type="button"
              onClick={() =>
                save({
                  scanner: {
                    ignore: ignore.split('\n').map((line) => line.trim()).filter(Boolean),
                    follow_symlinks: followSymlinks,
                    max_depth: Number(maxDepth) || 6,
                  },
                })
              }
              disabled={patchSettings.isPending}
              className="btn-primary px-5 py-2.5 text-[13px]"
            >
              {t('settings.scanner.save')}
            </button>
          </div>
        </div>
      </Section>

      <Section id="data" title={t('settings.sections.data')} icon={Database}>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="card p-5">
            <h3 className="text-[14px] font-semibold text-white">{t('settings.data.export')}</h3>
            <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-400">
              {t('settings.data.exportHint')}
            </p>
            <button
              type="button"
              onClick={doExport}
              disabled={exportData.isPending}
              className="btn-ghost mt-4 gap-1.5"
            >
              {exportData.isPending ? <Spinner className="h-4 w-4" /> : <Download className="h-4 w-4" />}
              {t('settings.data.export')}
            </button>
          </div>
          <div className="card p-5">
            <h3 className="text-[14px] font-semibold text-white">{t('settings.data.import')}</h3>
            <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-400">
              {t('settings.data.importHint')}
            </p>
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              disabled={importData.isPending}
              className="btn-ghost mt-4 gap-1.5"
            >
              {importData.isPending ? <Spinner className="h-4 w-4" /> : <Upload className="h-4 w-4" />}
              {t('settings.data.import')}
            </button>
            <input
              ref={fileInput}
              type="file"
              accept="application/json"
              hidden
              onChange={(event) => doImport(event.target.files?.[0])}
            />
          </div>
        </div>
      </Section>
    </>
  )
}
