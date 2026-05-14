import { getChatId, getInitData } from './tg';
import type {
  BalanceResponse,
  FarmState,
  GameResult,
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
  portfolio: () => request<{ items: PortfolioBet[] }>('/portfolio'),

  coinflip: (bet: number, pick: 'heads' | 'tails') =>
    request<GameResult>('/games/coinflip', {
      method: 'POST',
      body: JSON.stringify({ bet, pick })
    }),
  dice: (bet: number, mode: 'over' | 'under', threshold: number) =>
    request<GameResult>('/games/dice', {
      method: 'POST',
      body: JSON.stringify({ bet, mode, threshold })
    }),
  slots: (bet: number) =>
    request<GameResult>('/games/slots', {
      method: 'POST',
      body: JSON.stringify({ bet })
    }),
  roulette: (bet: number, bet_type: string, value: string | null) =>
    request<GameResult>('/games/roulette', {
      method: 'POST',
      body: JSON.stringify({ bet, bet_type, value })
    }),
  blackjackStart: (bet: number) =>
    request<GameResult>('/games/blackjack/start', {
      method: 'POST',
      body: JSON.stringify({ bet })
    }),
  blackjackHit: (gameId: number) =>
    request<GameResult>(`/games/blackjack/${gameId}/hit`, { method: 'POST' }),
  blackjackStand: (gameId: number) =>
    request<GameResult>(`/games/blackjack/${gameId}/stand`, { method: 'POST' }),
  blackjackDouble: (gameId: number) =>
    request<GameResult>(`/games/blackjack/${gameId}/double`, { method: 'POST' }),

  // ---------- admin ----------
  adminBalanceAdjust: (target: string, amount: number, note: string | null) =>
    request<{ user_id: number; username: string | null; new_balance: number }>(
      '/admin/balance_adjust',
      { method: 'POST', body: JSON.stringify({ target, amount, note }) }
    ),
  adminBankAdjust: (amount: number, note: string | null) =>
    request<{ new_balance: number }>('/admin/bank_adjust', {
      method: 'POST',
      body: JSON.stringify({ amount, note })
    }),
  adminMarketCreate: (body: { question: string; options: string[]; duration: string }) =>
    request<{ market_id: number; fee_charged: number; options: { id: number; label: string }[] }>(
      '/admin/markets/create',
      { method: 'POST', body: JSON.stringify(body) }
    ),
  adminMarketImport: (url: string) =>
    request<{ market_id: number; already_imported: boolean; [k: string]: any }>(
      '/admin/markets/import',
      { method: 'POST', body: JSON.stringify({ url }) }
    ),
  adminMarketResolve: (id: number, winning_option_position: number) =>
    request<Record<string, any>>(`/admin/markets/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ winning_option_position })
    }),
  adminMarketCancel: (id: number) =>
    request<Record<string, any>>(`/admin/markets/${id}/cancel`, { method: 'POST' }),

  // ---------- clicker farm ----------
  farmState: () => request<FarmState>('/farm'),
  farmTap: (count: number, elapsedMs: number) =>
    request<FarmState>('/farm/tap', {
      method: 'POST',
      body: JSON.stringify({ count, elapsed_ms: elapsedMs })
    }),
  farmUpgradeTap: () => request<FarmState>('/farm/upgrade/tap', { method: 'POST' }),
  farmUpgradeAuto: () => request<FarmState>('/farm/upgrade/auto', { method: 'POST' }),
  farmConvert: (hryvniaAmount: number) =>
    request<FarmState>('/farm/convert', {
      method: 'POST',
      body: JSON.stringify({ hryvnia_amount: hryvniaAmount })
    })
};
