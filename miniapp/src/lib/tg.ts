// Обёртка над Telegram.WebApp. В dev (вне TMA) возвращает stubs.

export function getTg(): TelegramWebApp | null {
  if (typeof window === 'undefined') return null;
  return window.Telegram?.WebApp ?? null;
}

export function getInitData(): string {
  const tg = getTg();
  return tg?.initData ?? '';
}

export function getChatId(): number | null {
  if (typeof window === 'undefined') return null;
  const params = new URLSearchParams(window.location.search);
  const cid = params.get('chat_id');
  return cid ? Number(cid) : null;
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
