import { QueryClient } from '@tanstack/react-query';

// queryClient 管理整个前端应用共享的查询缓存和请求状态。
export const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 60 * 1000,
            refetchOnWindowFocus: false,
        },
    },
});

type RequestOptions = {
    method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
    body?: unknown;
    dispatchUnauthorized?: boolean;
    signal?: AbortSignal;
};

export class ApiError extends Error {
    status: number;

    constructor(status: number, message: string) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
    }
}

export const apiUnauthorizedEvent = 'api:unauthorized';

let csrfToken: string | null = null;

export function setCSRFToken(value: string | null) {
    csrfToken = value;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const headers = new Headers(options.body === undefined ? undefined : { 'Content-Type': 'application/json' });
    if (csrfToken && options.method && options.method !== 'GET') {
        headers.set('X-CSRF-Token', csrfToken);
    }

    const response = await fetch(path, {
        method: options.method ?? 'GET',
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        credentials: 'include',
        signal: options.signal,
    });
    const data = await response.json().catch(() => null) as { message?: string; detail?: string; data?: T } | null;
    if (!response.ok) {
        if (response.status === 401 && options.dispatchUnauthorized !== false && typeof window !== 'undefined') {
            window.dispatchEvent(new Event(apiUnauthorizedEvent));
        }
        throw new ApiError(response.status, data?.message || data?.detail || `Request failed: ${response.status}`);
    }
    return data?.data as T;
}
