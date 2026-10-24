import { useEffect, useState } from 'react'
import { Play } from 'lucide-react'
import type { PlayMode } from '../../api/types'
import { useMyPlayer, usePatchMyPlayer } from '../../api/hooks'
import { useToast } from '../../store/ui'
import { Field, Section } from './common'

export function PlayerPreferenceSection() {
  const query = useMyPlayer()
  const patch = usePatchMyPlayer()
  const toast = useToast()
  const [inherit, setInherit] = useState(true)
  const [mode, setMode] = useState<PlayMode>('builtin')
  const bridge = window.StrmActionNative
  const native = Boolean(bridge?.isCompanion?.() || bridge?.isDesktop?.())
  useEffect(() => {
    if (!query.data) return
    setInherit(query.data.overrides.mode === null)
    setMode(query.data.overrides.mode ?? query.data.defaults.mode)
  }, [query.data])
  const save = async () => {
    try {
      await patch.mutateAsync({ mode: inherit ? null : mode })
      toast({ title: '播放方式已保存', tone: 'success' })
    } catch (error) {
      toast({ title: '保存失败', description: (error as Error).message, tone: 'error' })
    }
  }
  return (
    <Section id="player" title="我的播放方式" icon={Play}>
      <div className="card space-y-4 p-5">
        {query.isLoading ? <div className="skeleton h-20" /> : null}
        {query.error ? <button className="btn-ghost" onClick={() => query.refetch()}>加载失败，点击重试</button> : null}
        {query.data ? <>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={inherit} onChange={e => setInherit(e.target.checked)} />
            使用全局默认（{query.data.defaults.mode === 'copy' ? '复制链接' : '内部播放'}）
          </label>
          <Field label="账号默认播放方式" hint="设备设置中的本机覆盖优先于账号默认。">
            <select className="input" disabled={inherit} value={mode} onChange={e => setMode(e.target.value as PlayMode)}>
              <option value="builtin" disabled={!native}>内部播放{!native ? '（需要使用 App）' : ''}</option>
              <option value="copy">复制链接</option>
            </select>
          </Field>
          {!native ? <p className="text-xs text-ink-400">普通浏览器支持复制链接；内部播放请使用 StrmAction App。</p> : null}
          {bridge?.openSettings ? <button className="btn-ghost" onClick={() => bridge.openSettings?.()}>打开本机设置</button> : null}
          <div><button className="btn-primary" disabled={patch.isPending} onClick={save}>保存</button></div>
        </> : null}
      </div>
    </Section>
  )
}
