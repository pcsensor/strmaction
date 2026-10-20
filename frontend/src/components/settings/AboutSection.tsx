import { Info } from 'lucide-react'
import { useAbout } from '../../api/hooks'
import { t } from '../../i18n/zh-CN'
import { Spinner } from '../Spinner'
import { Section } from './common'

/** 关于：所有登录用户可见；数据目录由服务端仅对管理员返回。 */
export function AboutSection() {
  const aboutQuery = useAbout()
  const about = aboutQuery.data

  return (
    <Section id="about" title={t('settings.sections.about')} icon={Info}>
      <div className="card space-y-3 p-5 text-[12.5px] text-ink-300">
        {aboutQuery.isLoading ? (
          <div className="flex items-center gap-2 text-ink-400">
            <Spinner className="h-4 w-4" />
            {t('common.loading')}
          </div>
        ) : null}

        {!about && !aboutQuery.isLoading ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-rose-300">
              {t('settings.about.loadFailed')}：{(aboutQuery.error as Error)?.message}
            </span>
            <button
              type="button"
              onClick={() => aboutQuery.refetch()}
              className="btn-ghost px-4 py-2 text-[12px]"
            >
              {t('common.retry')}
            </button>
          </div>
        ) : null}

        {about ? (
          <>
            <div className="flex flex-wrap justify-between gap-2">
              <span>{t('settings.about.version')}</span>
              <span className="font-mono">{about.version}</span>
            </div>
            {about.data_dir ? (
              <div className="flex flex-wrap justify-between gap-2">
                <span>{t('settings.about.dataDir')}</span>
                <span className="break-all font-mono text-[11.5px]">{about.data_dir}</span>
              </div>
            ) : null}
            <div className="flex flex-wrap justify-between gap-2">
              <span>{t('settings.about.docs')}</span>
              <a
                href={about.api_docs || '/docs'}
                target="_blank"
                rel="noreferrer"
                className="text-accent hover:underline"
              >
                {about.api_docs || '/docs'}
              </a>
            </div>
            <p className="border-t border-white/8 pt-3 text-[11px] leading-relaxed text-ink-500">
              {t('settings.about.tmdbNotice')}
            </p>
            <p className="text-[11px] leading-relaxed text-ink-500">{t('settings.about.tvHint')}</p>
          </>
        ) : null}
      </div>
    </Section>
  )
}
