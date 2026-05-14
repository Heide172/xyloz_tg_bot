import { getChatId, getInitData } from './tg';
import type {
  BalanceResponse,
  LeaderboardEntry,
  Market,
  MeResponse,
  PortfolioBet,
  TxItem
} from './types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/$/, '');

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  headers.set('X-Telegram-Init-Data', getInitData());
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const chatId = getChatId();
  const url = new URL(path.startsWith('http') ? path : API_BASE + path, window.location.origin);
  if (chatId != null && !url.searchParams.has('chat_id')) {
    url.searchParams.set('chat_id', String(chatId));
  }

  const resp = await fetch(url.toString(), { ...init, headers });
  if (!resp.ok) {
    let detail = '';
    try {
      const body = await resp.json();
      detail = body?.detail ?? '';
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

export const api = {
  me: () => request<MeResponse>('/me'),
  balance: () => request<BalanceResponse>('/balance'),
  leaderboard: (limit = 20) => request<{ entries: LeaderboardEntry[] }>(`/leaderboard?limit=${limit}`),
  transactions: (limit = 50) => request<{ items: TxItem[] }>(`/transactions?limit=${limit}`),
  marketsList: (status: string = 'open') =>
    request<{ items: Market[] }>(`/markets?status=${status}`),
  market: (id: number) => request<Market>(`/markets/${id}`),
  createMarket: (body: { question: string; options: string[]; duration: string }) =>
    request<{ market: Market; fee_charged: number }>('/markets', {
      method: 'POST',
      body: JSON.stringify(body)
    }),
  placeBet: (id: number, body: { option_position: number; amount: number }) =>
    request<{
      bet_id: number;
      market_id: number;
      option_label: string;
      option_pool_after: number;
      user_balance_after: number;
    }>(`/markets/${id}/bets`, {
      method: 'POST',
      body: JSON.stringify(body)
    }),
  importMarket: (url: string) =>
    request<{ market: Market; already_imported: boolean }>('/markets/import', {
      method: 'POST',
      body: JSON.stringify({ url })
    }),
  portfolio: () => request<{ items: PortfolioBet[] }>('/portfolio')
};
