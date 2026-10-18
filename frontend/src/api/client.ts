export class ApiError extends Error {
  status: number
  code: string
  details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

type RequestOptions = {
  method?: string
  body?: unknown
  signal?: AbortSignal
  headers?: Record<string, string>
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, headers = {} } = options
  const init: RequestInit = {
    method,
    credentials: 'same-origin',
    signal,
    headers: { Accept: 'application/json', ...headers },
  }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { ...init.headers, 'Content-Type': 'application/json' }
  }

  let response: Response
  try {
    response = await fetch(path, init)
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    throw new ApiError(0, 'NETWORK', '网络请求失败，请检查服务是否在线')
  }

  if (response.status === 401) {
    if (!path.startsWith('/api/auth/')) {
      window.dispatchEvent(new CustomEvent('strmaction:unauthorized'))
    }
  }

  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text()

  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string } })?.error
    throw new ApiError(
      response.status,
      error?.code || `HTTP_${response.status}`,
      error?.message || (typeof payload === 'string' ? payload : '请求失败'),
      payload,
    )
  }
  return payload as T
}

export const api = {
  get<T>(path: string, signal?: AbortSignal) {
    return request<T>(path, { signal })
  },
  post<T>(path: string, body?: unknown, signal?: AbortSignal) {
    return request<T>(path, { method: 'POST', body, signal })
  },
  patch<T>(path: string, body?: unknown) {
    return request<T>(path, { method: 'PATCH', body })
  },
  delete<T>(path: string) {
    return request<T>(path, { method: 'DELETE' })
  },
  upload<T>(path: string, form: FormData) {
    return request<T>(path, { method: 'POST', body: form })
  },
}

export function buildQuery(params: Record<string, string | number | boolean | undefined | null>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}
