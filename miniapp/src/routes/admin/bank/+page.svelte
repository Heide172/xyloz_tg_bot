<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';
  import type { BalanceResponse } from '$lib/types';

  let balance: BalanceResponse | null = null;
  let amount = 1000;
  let note = '';
  let busy = false;

  onMount(async () => {
    try {
      balance = await api.balance();
    } catch (e: any) {
      showAlert(e?.message ?? 'Не удалось');
    }
  });

  async function submit() {
    if (busy) return;
    if (!amount) {
      showAlert('Сумма не может быть нулевой');
      return;
    }
    busy = true;
    try {
      const r = await api.adminBankAdjust(amount, note.trim() || null);
      if (balance) balance = { ...balance, bank: r.new_balance };
      haptic('success');
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busy = false;
    }
  }

  $: search = typeof window !== 'undefined' ? window.location.search : '';
</script>

<a class="back" href={`/admin${search}`}>← к админке</a>
<h1 class="h1">Банк чата</h1>

<section class="card">
  {#if balance}
    <div class="cur muted">
      Сейчас в банке: <strong style="color: var(--text)">{fmtCoins(balance.bank)}</strong>
    </div>
  {/if}

  <label class="lbl">
    <span class="muted small">Корректировка (±)</span>
    <input type="number" step="100" bind:value={amount} />
    <div class="muted small">Положительное — добавить в банк (out of thin air). Отрицательное — изъять.</div>
  </label>
  <label class="lbl">
    <span class="muted small">Комментарий</span>
    <input type="text" placeholder="назначение" bind:value={note} />
  </label>

  <button class="play" disabled={busy} on:click={submit}>
    {busy ? 'Применяю…' : 'Применить'}
  </button>
</section>

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .cur { font-size: 14px; margin-bottom: 14px; }
  .small { font-size: 12px; }
  .lbl { display: block; margin-bottom: 14px; }
  .lbl span { display: block; margin-bottom: 6px; }
  .lbl input {
    width: 100%; padding: 11px 12px; border: 1px solid var(--separator);
    border-radius: 9px; font-size: 16px; background: var(--bg); color: var(--text);
  }
  .play {
    width: 100%; padding: 14px; background: var(--accent); color: var(--accent-text);
    border: 0; border-radius: 10px; font-weight: 700; font-size: 15px; cursor: pointer;
  }
  .play:disabled { opacity: 0.6; }
</style>
