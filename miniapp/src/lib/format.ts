export function fmtCoins(n: number): string {
  return Intl.NumberFormat('ru-RU').format(n);
}

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
}

export function fmtPct(share: number): string {
  return `${(share * 100).toFixed(1)}%`;
}

export function shortLabel(s: string, max = 60): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + '…';
}
