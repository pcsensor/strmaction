import type { CastMember } from '../api/types'
import { ImageWithFallback } from './ImageWithFallback'
import { t } from '../i18n/zh-CN'

function avatarSrc(member: CastMember): string | null {
  if (member.avatar) return `/img/${member.avatar}_185.webp`
  return member.avatar_url || null
}

export function CastRow({ cast }: { cast: CastMember[] }) {
  if (!cast?.length) return null
  return (
    <section>
      <h2 className="section-title mb-5">{t('detail.cast')}</h2>
      <div className="no-scrollbar flex gap-5 overflow-x-auto pb-2">
        {cast.map((member, index) => (
          <div
            key={`${member.name}-${index}`}
            className="w-[92px] shrink-0 text-center"
          >
            <ImageWithFallback
              src={avatarSrc(member)}
              alt={member.name}
              className="mx-auto h-[92px] w-[92px] rounded-full border border-white/10"
              imgClassName="rounded-full"
            />
            <p className="mt-2.5 line-clamp-1 text-[12.5px] font-medium text-ink-100">
              {member.name}
            </p>
            {member.role ? (
              <p className="mt-0.5 line-clamp-1 text-[10.5px] text-ink-400">{member.role}</p>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  )
}
