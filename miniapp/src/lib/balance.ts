/**
 * Глобальный кэш баланса. Сидируется один раз (api.me / api.balance),
 * обновляется оптимистично из ответов экшенов (sniffBalance в request())
 * и пушами SSE. Экраны подписываются на store вместо повторных запросов.
 */
import { writable } from 'svelte/store';

export interface BalanceState {
  balance: number | null;
  bank: number | null;
  updatedAt: number;
}

export const balanceStore = writable<BalanceState>({
  balance: null,
  bank: null,
  updatedAt: 0
});

export function setBalance(
  balance: number | null | undefined,
  bank?: number | null | undefined
) {
  balanceStore.update((s) => ({
    balance: typeof balance === 'number' ? balance : s.balance,
    bank: typeof bank === 'number' ? bank : s.bank,
    updatedAt: Date.now()
  }));
}

/** /me → { user, balance: { balance, bank } } */
export function seedFromMe(me: any) {
  if (me?.balance) setBalance(me.balance.balance, me.balance.bank);
}

/** Подсмотреть баланс в ответе любого экшена (узкий список ключей,
 *  чтобы не спутать с cp_balance фермы и т.п.). */
export function sniffBalance(obj: any) {
  if (!obj || typeof obj !== 'object') return;
  const b =
    obj.user_balance ??
    obj.new_balance ??
    obj.user_balance_after ??
    obj.sender_balance;
  const bank = obj.bank ?? obj.bank_balance;
  if (typeof b === 'number' || typeof bank === 'number') {
    setBalance(typeof b === 'number' ? b : undefined, bank);
  }
}
