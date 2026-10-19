import { appUrl } from './url'

export interface ApiError extends Error {
  code?: number
}

let refreshing: Promise<boolean> | null = null

async function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(appUrl('/api/auth/refresh'), {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' },
          body: '{}',
        })
        return res.ok
      } catch {
        return false
      } finally {
        refreshing = null
      }
    })()
  }
  return refreshing
}

async function request<T = any>(url: string, options: RequestInit = {}, retry = true): Promise<T> {
  const res = await fetch(appUrl(url), {
    credentials: 'same-origin',
    ...options,
    // headers 放在 options 之后合并，调用方自定义头不会整体覆盖默认头
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'fetch',
      ...((options.headers as Record<string, string>) || {}),
    },
  })
  let data: any
  try {
    data = await res.json()
  } catch {
    throw new Error('服务响应异常')
  }
  if (!res.ok || data.code !== 0) {
    const err = new Error(data?.msg || '请求失败') as ApiError
    err.code = data?.code ?? res.status
    if (err.code === 401 && !url.includes('/api/auth/login')
        && !url.includes('/api/auth/refresh')) {
      if (retry && await refreshSession()) {
        return request<T>(url, options, false)
      }
      if (window.location.pathname !== appUrl('/login')) {
        window.location.href = appUrl('/login')
      }
    }
    // 后端强制改密（4031）：引导到个人中心，避免用户在各页面反复撞 403
    if (err.code === 4031 && !window.location.pathname.startsWith(appUrl('/profile'))) {
      window.location.href = appUrl('/profile')
    }
    throw err
  }
  return data.data as T
}

export const api = {
  get: <T = any>(url: string) => request<T>(url),
  post: <T = any>(url: string, body?: any) =>
    request<T>(url, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  put: <T = any>(url: string, body?: any) =>
    request<T>(url, { method: 'PUT', body: JSON.stringify(body ?? {}) }),
  del: <T = any>(url: string) => request<T>(url, { method: 'DELETE' }),
}

export function downloadUrl(url: string) {
  window.location.href = appUrl(url)
}
