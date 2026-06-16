import { getChatId, getInitData } from './tg';
import { seedFromMe, setBalance, sniffBalance } from './balance';
import { track } from './analytics';
import { isDownStatus, markDown, markUp } from './service';
import type {
  BalanceResponse,
  FarmState,
  GameResult,
  HistoryItem,
  LeaderboardEntry,
  Market,
  MeResponse,
  PortfolioBet,
  TxItem
} from './types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api/v1').replace(/\/$/, '');

async function extractError(resp: Response): Promise<string> {
  let body: any = null;
  try {
    body = await resp.json();
  } catch {
    try {
      const t = (await resp.text())?.trim();
      if (t) return t.slice(0, 300);
    } catch {
      /* ignore */
    }
    return `HTTP ${resp.status}`;
  }
  const d = body?.detail ?? body?.message ?? body;
  if (typeof d === 'string') return d || `HTTP ${resp.status}`;
  // FastAPI 422: detail = [{loc,msg,type}, ...]
  if (Array.isArray(d)) {
    const msgs = d
      .map((e) => (typeof e === 'string' ? e : e?.msg))
      .filter(Boolean);
    if (msgs.length) return msgs.join('; ');
  }
  if (d && typeof d === 'object') {
    if (typeof d.msg === 'string') return d.msg;
    try {
      return JSON.stringify(d).slice(0, 300);
    } catch {
      /* ignore */
    }
  }
  return `HTTP ${resp.status}`;
}

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

  let resp: Response;
  try {
    resp = await fetch(url.toString(), { ...init, headers });
  } catch (e) {
    // network error → бэкенд недоступен (редеплой / сеть)
    markDown();
    throw e;
  }
  if (!resp.ok) {
    if (isDownStatus(resp.status)) markDown();
    throw new Error(await extractError(resp));
  }
  markUp(); // успешный ответ — сервис жив
  const data = await resp.json();
  // Глобальный кэш баланса: подхватываем из любого ответа.
  try {
    if (path === '/me') seedFromMe(data);
    else if (path === '/balance')
      setBalance(data?.balance, data?.bank);
    else sniffBalance(data);
  } catch {
    /* кэш баланса не должен ломать запрос */
  }
  // Авто-трекинг действий: успешные POST (кроме самого /event).
  if ((init.method ?? 'GET').toUpperCase() === 'POST' && path !== '/event') {
    track('action', { name: path });
  }
  return data as T;
}

export const api = {
  me: () => request<MeResponse>('/me'),
  balance: () => request<BalanceResponse>('/balance'),
  leaderboard: (limit = 20) => request<{ entries: LeaderboardEntry[] }>(`/leaderboard?limit=${limit}`),
  transactions: (limit = 50) => request<{ items: TxItem[] }>(`/transactions?limit=${limit}`),
  feedback: (kind: 'bug' | 'idea', text: string) =>
    request<{ ok: boolean }>('/feedback', {
      method: 'POST',
      body: JSON.stringify({ kind, text })
    }),
  feedbackAssist: (message: string) =>
    request<{
      reply: string;
      registered: { id: number; kind: 'bug' | 'idea' } | null;
      degraded?: boolean;
    }>('/feedback/assist', {
      method: 'POST',
      body: JSON.stringify({ message })
    }),
  feedbackMine: () =>
    request<{
      items: {
        id: number;
        kind: 'bug' | 'idea';
        status: string;
        text: string;
        reward: number;
        default_reward: number;
        created_at: string | null;
        rewarded_at: string | null;
      }[];
    }>('/feedback/mine'),
  gachaCollection: () => request<any>('/gacha/collection'),
  gachaRoll: (count: number) =>
    request<any>('/gacha/roll', { method: 'POST', body: JSON.stringify({ count }) }),
  gachaSetHeroine: (char_id: string) =>
    request<any>('/gacha/heroine', { method: 'POST', body: JSON.stringify({ char_id }) }),
  gachaDaily: () =>
    request<{ claimed: boolean; amount: number; gems: number; daily_available: boolean }>(
      '/gacha/daily',
      { method: 'POST' }
    ),
  gachaPet: (char_id: string) =>
    request<{ char_id: string; affection: number; bond: number; line: string }>('/gacha/pet', {
      method: 'POST',
      body: JSON.stringify({ char_id })
    }),
  gachaBuyGems: (gems: number) =>
    request<{ bought: number; spent_cp: number; gems: number; cp_balance: number }>(
      '/gacha/gems/buy',
      { method: 'POST', body: JSON.stringify({ gems }) }
    ),
  gachaArena: () => request<any>('/gacha/arena', { method: 'POST' }),
  gachaPvpQueue: () => request<any>('/gacha/pvp/queue', { method: 'POST' }),
  gachaPvpCancel: () => request<any>('/gacha/pvp/cancel', { method: 'POST' }),
  gachaPvpLadder: () => request<any>('/gacha/pvp/ladder'),
  gachaStarsInvoice: (stars: number) =>
    request<{ url: string; stars: number; hryvnia: number; rate: number }>(
      '/gacha/stars_invoice',
      { method: 'POST', body: JSON.stringify({ stars }) }
    ),
  tagsState: () => request<any>('/tags/state'),
  tagsRent: (title: string, days: number, giftTo: string | null = null) =>
    request<{
      title: string;
      expires_at: string;
      price: number;
      user_balance: number;
      gift: boolean;
      recipient_tg_id: number | null;
      tg_applied: boolean;
      tg_error: string | null;
    }>('/tags/rent', {
      method: 'POST',
      body: JSON.stringify({ title, days, gift_to: giftTo })
    }),
  tagsCancel: () =>
    request<{ ok: boolean; tg_applied: boolean; tg_error: string | null }>(
      '/tags/cancel',
      { method: 'POST' }
    ),
  tagsReapply: () =>
    request<{
      ok: boolean;
      title: string;
      tg_applied: boolean;
      tg_error: string | null;
    }>('/tags/reapply', { method: 'POST' }),
  duelList: () => request<any>('/duel/list'),
  duelChallenge: (opponent: string, stake: number) =>
    request<any>('/duel/challenge', {
      method: 'POST',
      body: JSON.stringify({ opponent, stake })
    }),
  duelAccept: (id: number) => request<any>(`/duel/${id}/accept`, { method: 'POST' }),
  duelDecline: (id: number) => request<any>(`/duel/${id}/decline`, { method: 'POST' }),
  duelCancel: (id: number) => request<any>(`/duel/${id}/cancel`, { method: 'POST' }),
  shopPrices: () =>
    request<{ poke: number; joke: number; roast: number }>('/social/prices'),
  shopPoke: (target: string, kind: string) =>
    request<{ text: string; cost: number; user_balance: number }>('/social/poke', {
      method: 'POST',
      body: JSON.stringify({ target, kind })
    }),
  shopJoke: (topic: string) =>
    request<{ text: string; cost: number; user_balance: number }>('/social/joke', {
      method: 'POST',
      body: JSON.stringify({ topic })
    }),
  shopRoast: (target: string) =>
    request<{ text: string; cost: number; user_balance: number }>('/social/roast', {
      method: 'POST',
      body: JSON.stringify({ target })
    }),
  stats: () =>
    request<{
      players: {
        tg_id: number;
        username: string | null;
        fullname: string | null;
        balance: number;
        casino_net: number;
        casino_staked: number;
        casino_won: number;
        farm_earned: number;
        games_played: number;
      }[];
      biggest_wins: {
        username: string | null;
        fullname: string | null;
        game: string;
        bet: number;
        payout: number;
        created_at: string;
      }[];
    }>('/stats'),
  members: (q = '') =>
    request<{ items: { tg_id: number; username: string | null; fullname: string | null }[] }>(
      `/members?q=${encodeURIComponent(q)}`
    ),
  transferQuote: (amount: number) =>
    request<{ amount: number; fee: number; total: number }>(
      `/transfer/quote?amount=${amount}`
    ),
  transfer: (target: string, amount: number, note: string | null) =>
    request<{
      amount: number;
      fee: number;
      total: number;
      sender_balance: number;
      receiver_balance: number;
      receiver_username: string | null;
    }>('/transfer', {
      method: 'POST',
      body: JSON.stringify({ target, amount, note })
    }),
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
  slots: (bet: number, idemKey?: string) =>
    request<GameResult>('/games/slots', {
      method: 'POST',
      body: JSON.stringify({ bet, idem_key: idemKey })
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
  adminMarketResolve: (id: number, winning_option_position: number) =>
    request<Record<string, any>>(`/admin/markets/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ winning_option_position })
    }),
  adminMarketCancel: (id: number) =>
    request<Record<string, any>>(`/admin/markets/${id}/cancel`, { method: 'POST' }),
  adminAnalytics: (hours = 24) =>
    request<{
      hours: number;
      total: number;
      unique_users: number;
      views: { name: string; n: number }[];
      actions: { name: string; n: number }[];
    }>(`/admin/analytics?hours=${hours}`),
  adminMetrics: () =>
    request<{
      enabled: boolean;
      routes: {
        route: string;
        method: string;
        n: number;
        avg_ms: number;
        max_ms: number;
        err4: number;
        err5: number;
        p50: string;
        p95: string;
      }[];
      pool: Record<string, string>;
    }>('/admin/metrics'),
  adminTwinStatus: () =>
    request<{
      state: {
        chat_id: number;
        target_user_id: number | null;
        target_tg_id: number | null;
        target_name: string | null;
        day_msk: string | null;
        enabled: boolean;
        paused_until: string | null;
        replies_today: number;
        last_reply_at: string | null;
        persona_stats: Record<string, any>;
      } | null;
      logs: {
        id: number;
        text: string;
        status: string;
        cost: number;
        created_at: string | null;
      }[];
    }>('/admin/twin'),
  adminTwinToggle: (enabled: boolean) =>
    request<{ enabled: boolean }>('/admin/twin/toggle', {
      method: 'POST',
      body: JSON.stringify({ enabled })
    }),
  adminTwinRotateNow: () =>
    request<{ target: any }>('/admin/twin/rotate_now', { method: 'POST' }),
  adminTwinSetTarget: (target: string) =>
    request<{ target: any }>('/admin/twin/set_target', {
      method: 'POST',
      body: JSON.stringify({ target })
    }),
  adminFeedbackList: () =>
    request<{
      items: {
        id: number;
        kind: 'bug' | 'idea';
        status: string;
        text: string;
        chat_id: number | null;
        created_at: string | null;
        default_reward: number;
      }[];
    }>('/admin/feedback'),
  adminFeedbackClose: (id: number, amount: number | null) =>
    request<{
      ok: boolean;
      id: number;
      kind: string;
      reward: number;
      credited: boolean;
      chat_id: number | null;
      author_name: string | null;
    }>(`/admin/feedback/${id}/close`, {
      method: 'POST',
      body: JSON.stringify({ amount })
    }),

  // ---------- clicker farm ----------
  farmState: () => request<FarmState>('/farm'),
  farmTap: (count: number, elapsedMs: number) =>
    request<FarmState>('/farm/tap', {
      method: 'POST',
      body: JSON.stringify({ count, elapsed_ms: elapsedMs })
    }),
  farmUpgradeTap: () => request<FarmState>('/farm/upgrade/tap', { method: 'POST' }),
  farmUpgradeAuto: () => request<FarmState>('/farm/upgrade/auto', { method: 'POST' }),
  farmHire: (wtype: string) =>
    request<FarmState>(`/farm/hire/${wtype}`, { method: 'POST' }),
  farmConvert: (cpAmount: number) =>
    request<FarmState>('/farm/convert', {
      method: 'POST',
      body: JSON.stringify({ cp_amount: cpAmount })
    }),
  farmBuyCp: (hryvniaAmount: number) =>
    request<FarmState>('/farm/buy', {
      method: 'POST',
      body: JSON.stringify({ hryvnia_amount: hryvniaAmount })
    }),
  farmMarket: () =>
    request<{
      rate: number;
      r_cp: number;
      r_h: number;
      anchor_rate: number;
      history: { ts: string; rate: number }[];
    }>('/farm/market'),

  history: (limit = 50, offset = 0) =>
    request<{ items: HistoryItem[]; has_more: boolean }>(
      `/history?limit=${limit}&offset=${offset}`
    )
};
