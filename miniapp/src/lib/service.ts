/**
 * Глобальное состояние доступности бэкенда. Когда API недоступен
 * (редеплой: 502/503/504 или network error) — показываем красивую
 * заглушку вместо ошибок, и автоматически восстанавливаемся.
 */
import { writable } from 'svelte/store';

export type ServiceState = 'ok' | 'updating';
export const serviceState = writable<ServiceState>('ok');

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/$/, '');
let _state: ServiceState = 'ok';
let _poll: ReturnType<typeof setInterval> | null = null;

serviceState.subscribe((s) => (_state = s));

export function markUp() {
  if (_state !== 'ok') serviceState.set('ok');
  if (_poll) {
    clearInterval(_poll);
    _poll = null;
  }
}

export function markDown() {
  if (_state !== 'updating') serviceState.set('updating');
  if (_poll || typeof window === 'undefined') return;
  // Пингуем дешёвый публичный эндпоинт, пока не оживёт.
  _poll = setInterval(async () => {
    try {
      const r = await fetch(`${API_BASE}/ping`, { cache: 'no-store' });
      if (r.ok) markUp();
    } catch {
      /* ещё лежит */
    }
  }, 4000);
}

/** true, если ошибка похожа на «сервис недоступен» (редеплой). */
export function isDownStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}
