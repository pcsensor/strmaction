import { useState } from 'react'
import { AlertTriangle, Lock, ShieldCheck } from 'lucide-react'
import { useChangePassword } from '../../api/hooks'
import { useToast } from '../../store/ui'
import { t } from '../../i18n/zh-CN'
import { Field, Section } from './common'

/** 修改当前登录用户的密码（管理员与普通用户都可用）。 */
export function SecuritySection() {
  const changePassword = useChangePassword()
  const toast = useToast()

  const [passwordForm, setPasswordForm] = useState({ current: '', next: '', confirm: '' })
  const [passwordError, setPasswordError] = useState<string | null>(null)

  const submitPassword = async () => {
    setPasswordError(null)
    if (passwordForm.next.length < 8) {
      setPasswordError(t('settings.security.minLength'))
      return
    }
    if (passwordForm.next !== passwordForm.confirm) {
      setPasswordError(t('settings.security.mismatch'))
      return
    }
    try {
      await changePassword.mutateAsync({
        current_password: passwordForm.current,
        new_password: passwordForm.next,
      })
      setPasswordForm({ current: '', next: '', confirm: '' })
      toast({ title: t('settings.security.changed'), tone: 'success' })
    } catch (error) {
      setPasswordError((error as Error).message)
    }
  }

  return (
    <Section
      id="security"
      title={t('settings.sections.security')}
      description={t('settings.security.hint')}
      icon={ShieldCheck}
    >
      <div className="card max-w-2xl p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Field label={t('settings.security.currentPassword')}>
              <input
                className="input"
                type="password"
                autoComplete="current-password"
                value={passwordForm.current}
                onChange={(event) =>
                  setPasswordForm((prev) => ({ ...prev, current: event.target.value }))
                }
              />
            </Field>
          </div>
          <Field label={t('settings.security.newPassword')}>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={passwordForm.next}
              onChange={(event) =>
                setPasswordForm((prev) => ({ ...prev, next: event.target.value }))
              }
            />
          </Field>
          <Field label={t('settings.security.confirmPassword')}>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={passwordForm.confirm}
              onChange={(event) =>
                setPasswordForm((prev) => ({ ...prev, confirm: event.target.value }))
              }
            />
          </Field>
        </div>
        {passwordError ? (
          <p className="mt-3 flex items-center gap-1.5 text-[11.5px] text-rose-300">
            <AlertTriangle className="h-3.5 w-3.5" />
            {passwordError}
          </p>
        ) : null}
        <button
          type="button"
          onClick={submitPassword}
          disabled={changePassword.isPending}
          className="btn-primary mt-4 gap-1.5 px-5 py-2.5 text-[13px]"
        >
          <Lock className="h-3.5 w-3.5" />
          {t('settings.security.change')}
        </button>
      </div>
    </Section>
  )
}
