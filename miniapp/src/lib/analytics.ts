/**
 * Лёгкая usage-аналитика: fire-and-forget POST /event.
 * Никогда не блокирует и не роняет UI (ошибки глотаем).
 */
import { getChatId, getInitData } from './tg';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/$/, '');

let lastView = '';

export function track(event: 'view' | 'action', props: Record<string, any> = {}) {
  if (typeof window === 'undefined') return;
  // дедуп повторных view одного и того же роута подряд
  if (event === 'view') {
    const r = String(props.route ?? '');
    if (r === lastView) return;
    lastView = r;
  }
  try {
    const initData = getInitData();
    if (!initData) return;
    const url = new URL(API_BASE + '/event', window.location.origin);
    const chatId = getChatId();
    if (chatId != null) url.searchParams.set('chat_id', String(chatId));
    fetch(url.toString(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Telegram-Init-Data': initData
      },
      body: JSON.stringify({ event, props }),
      keepalive: true
    }).catch(() => {});
  } catch {
    /* ignore */
  }
}
