interface Props {
  className?: string
  rounded?: string
}

export function Skeleton({ className = '', rounded = 'rounded-xl' }: Props) {
  return <div className={`skeleton ${rounded} ${className}`} />
}

export function PosterSkeleton({ className = '' }: { className?: string }) {
  return (
    <div className={`w-[150px] shrink-0 sm:w-[176px] ${className}`}>
      <Skeleton className="aspect-[2/3] w-full" />
      <Skeleton className="mt-3 h-3.5 w-4/5" rounded="rounded-md" />
      <Skeleton className="mt-2 h-3 w-1/3" rounded="rounded-md" />
    </div>
  )
}

export function RowSkeleton({ count = 7 }: { count?: number }) {
  return (
    <div className="space-y-4">
      <Skeleton className="h-6 w-36" rounded="rounded-lg" />
      <div className="flex gap-4 overflow-hidden">
        {Array.from({ length: count }).map((_, index) => (
          <PosterSkeleton key={index} />
        ))}
      </div>
    </div>
  )
}

export function HeroSkeleton() {
  return (
    <div className="relative flex min-h-[64vh] items-end overflow-hidden pb-16">
      <Skeleton className="absolute inset-0" rounded="rounded-none" />
      <div className="relative z-10 w-full px-6 sm:px-10 lg:px-16">
        <Skeleton className="h-4 w-28" rounded="rounded-md" />
        <Skeleton className="mt-6 h-14 w-[min(560px,82%)]" rounded="rounded-2xl" />
        <Skeleton className="mt-4 h-4 w-[min(420px,70%)]" rounded="rounded-md" />
        <Skeleton className="mt-2 h-4 w-[min(360px,60%)]" rounded="rounded-md" />
        <div className="mt-8 flex gap-3">
          <Skeleton className="h-12 w-32" rounded="rounded-full" />
          <Skeleton className="h-12 w-32" rounded="rounded-full" />
        </div>
      </div>
    </div>
  )
}

export function DetailSkeleton() {
  return (
    <div className="min-h-screen pt-24">
      <div className="px-6 sm:px-10 lg:px-16">
        <div className="flex flex-col gap-8 md:flex-row">
          <Skeleton className="aspect-[2/3] w-[200px] shrink-0" />
          <div className="w-full space-y-4 pt-2">
            <Skeleton className="h-12 w-2/3" rounded="rounded-xl" />
            <Skeleton className="h-4 w-1/3" rounded="rounded-md" />
            <Skeleton className="h-4 w-full" rounded="rounded-md" />
            <Skeleton className="h-4 w-11/12" rounded="rounded-md" />
            <Skeleton className="h-4 w-4/5" rounded="rounded-md" />
            <Skeleton className="h-12 w-40" rounded="rounded-full" />
          </div>
        </div>
      </div>
      <div className="mt-12 px-6 sm:px-10 lg:px-16">
        <RowSkeleton count={6} />
      </div>
    </div>
  )
}
