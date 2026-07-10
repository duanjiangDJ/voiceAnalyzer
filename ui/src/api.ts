/**
 * api.ts — 统一 HTTP 客户端
 * ==========================
 * 封装 fetch，提供统一的错误处理、toast 通知和下载支持。
 * 所有 API 响应约定为 { success: bool, data: T, error?: string }。
 */

// ---------- Toast 通知系统 ----------

export interface ToastMessage {
  id: number;
  text: string;
  level: 'success' | 'error' | 'warning' | 'info';
}

let _toastId = 0;
let _toastSubscriber: ((msg: ToastMessage) => void) | null = null;

/** 订阅 toast 消息（由 App.vue 调用）。 */
export function onToast(fn: (msg: ToastMessage) => void): void {
  _toastSubscriber = fn;
}

function emitToast(text: string, level: ToastMessage['level'] = 'info'): void {
  const msg: ToastMessage = { id: ++_toastId, text, level };
  _toastSubscriber?.(msg);
}

// ---------- API 响应类型 ----------

export interface ApiEnvelope<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

// ---------- 内部 fetch 封装 ----------

const DEFAULT_TIMEOUT = 30_000;  // 30 秒超时

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(timer);
    if (!response.ok) {
      const detail = `HTTP ${response.status}: ${response.statusText}`;
      emitToast(detail, 'error');
      throw new Error(detail);
    }
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      const body: ApiEnvelope<T> = await response.json();
      if (body.success === false && body.error) {
        emitToast(body.error, 'error');
        throw new Error(body.error);
      }
      return (body.data ?? body) as T;
    }
    return response as unknown as T;
  } catch (err: unknown) {
    clearTimeout(timer);
    if (err instanceof DOMException && err.name === 'AbortError') {
      emitToast('请求超时，请检查网络或服务状态', 'warning');
    }
    throw err;
  }
}

// ---------- 公开 API ----------

export function apiGet<T>(url: string): Promise<T> {
  return request<T>(url);
}

export function apiPost<T>(url: string, body: unknown = {}): Promise<T> {
  return request<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function apiPut<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export function apiDelete<T>(url: string): Promise<T> {
  return request<T>(url, { method: 'DELETE' });
}

export function uploadForm<T>(url: string, formData: FormData): Promise<T> {
  return request<T>(url, { method: 'POST', body: formData });
}

/** Blob 下载（不离开页面）。 */
export async function downloadBlob(url: string, filename?: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) {
    emitToast(`下载失败: HTTP ${response.status}`, 'error');
    return;
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename || '';
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(objectUrl);
}

/** 直接 URL 下载（保留用于特殊情况）。 */
export function downloadUrl(path: string): void {
  const anchor = document.createElement('a');
  anchor.href = path;
  anchor.download = '';
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
}

// ---------- Toast 辅助 ----------

export const toast = {
  success: (text: string) => emitToast(text, 'success'),
  error: (text: string) => emitToast(text, 'error'),
  warning: (text: string) => emitToast(text, 'warning'),
  info: (text: string) => emitToast(text, 'info'),
};
