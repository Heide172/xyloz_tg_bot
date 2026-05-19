/**
 * SSE-подписка на пуш баланса. EventSource не умеет заголовки —
 * initData и chat_id идут query-параметрами. EventSource сам
 * реконнектит; держим один инстанс на сессию.
 */
import { setBalance } from './balance';
import { getChatId, getInitData } from './tg';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/$/, '');

let es: EventSource | null = null;

export function startBalanceSSE() {
  if (typeof window === 'undefined' || es) return;
  const initData = getInitData();
  const chatId = getChatId();
  if (!initData || chatId == null) return;

  const url = new URL(API_BASE + '/events', window.location.origin);
  url.searchParams.set('init_data', initData);
  url.searchParams.set('chat_id', String(chatId));

  try {
    es = new EventSource(url.toString());
  } catch {
    return;
  }
  es.onmessage = (ev) => {
    try {
      const d = JSON.parse(ev.data);
      if (typeof d?.balance === 'number') setBalance(d.balance);
    } catch {
      /* ignore */
    }
  };
  // onerror: EventSource сам переподключится; глушим, чтобы не спамить.
  es.onerror = () => {};
}

export function stopBalanceSSE() {
  es?.close();
  es = null;
}
