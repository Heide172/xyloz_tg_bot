// Обёртка над Telegram.WebApp. В dev (вне TMA) возвращает stubs.

export function getTg(): TelegramWebApp | null {
  if (typeof window === 'undefined') return null;
  return window.Telegram?.WebApp ?? null;
}

export function getInitData(): string {
  const tg = getTg();
  return tg?.initData ?? '';
}

/** start_param: "<chat_id>" или "<chat_id>_<route>" (route = duel, ...). */
function parseStartParam(): { chatId: number | null; route: string | null } {
  const sp = getTg()?.initDataUnsafe?.start_param;
  if (!sp) return { chatId: null, route: null };
  const m = sp.match(/^(-?\d+)(?:_([a-z]+))?$/);
  if (!m) {
    const n = Number(sp);
    return { chatId: Number.isFinite(n) ? n : null, route: null };
  }
  const chatId = Number(m[1]);
  return {
    chatId: Number.isFinite(chatId) && Math.abs(chatId) > 100 ? chatId : null,
    route: m[2] ?? null
  };
}

export function getChatId(): number | null {
  if (typeof window === 'undefined') return null;
  const fromStart = parseStartParam().chatId;
  if (fromStart !== null) return fromStart;
  const params = new URLSearchParams(window.location.search);
  const cid = params.get('chat_id');
  return cid ? Number(cid) : null;
}

/** Целевой роут из start_param (whitelist), для deep-link в раздел. */
export function getStartRoute(): string | null {
  const r = parseStartParam().route;
  const allowed: Record<string, string> = {
    duel: '/duel',
    farm: '/farm',
    gacha: '/gacha',
    games: '/games',
    markets: '/markets',
    shop: '/shop',
    tags: '/tags'
  };
  return r ? allowed[r] ?? null : null;
}

export function tgReady() {
  const tg = getTg();
  if (!tg) return;
  try {
    tg.ready();
    tg.expand();
  } catch {
    /* ignore */
  }
}

export function showAlert(text: string) {
  const tg = getTg();
  if (tg?.showAlert) tg.showAlert(text);
  else alert(text);
}

export function haptic(type: 'light' | 'medium' | 'heavy' | 'success' | 'error' | 'warning') {
  const tg = getTg();
  if (!tg) return;
  if (type === 'success' || type === 'error' || type === 'warning') {
    tg.HapticFeedback?.notificationOccurred(type);
  } else {
    tg.HapticFeedback?.impactOccurred(type);
  }
}
