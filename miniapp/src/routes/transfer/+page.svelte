<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';
  import type { BalanceResponse, LeaderboardEntry } from '$lib/types';

  let balance: BalanceResponse | null = null;
  let people: LeaderboardEntry[] = [];
  let target = '';
  let amount = 100;
  let note = '';
  let busy = false;
  let err: string | null = null;
  let done: { amount: number; fee: number; to: string } | null = null;

  $: fee = amount > 0 ? Math.max(1, Math.ceil(amount * 0.05)) : 0; // 5%, мин 1 (зеркалит сервер)
  $: total = amount + fee;
  $: search = typeof window !== 'undefined' ? window.location.search : '';

  onMount(async () => {
    try {
      [balance, people] = await Promise.all([
        api.balance(),
        api.leaderboard(30).then((r) => r.entries)
      ]);
    } catch (e: any) {
      err = e?.message;
    }
  });

  function pick(u: { username: string | null; tg_id: number }) {
    target = u.username ? '@' + u.username : String(u.tg_id);
  }

  async function send() {
    if (busy) return;
    if (!target.trim()) {
      showAlert('Укажи получателя');
      return;
    }
    if (amount < 1) {
      showAlert('Сумма должна быть > 0');
      return;
    }
    busy = true;
    err = null;
    try {
      const r = await api.transfer(target.trim(), amount, note.trim() || null);
      done = {
        amount: r.amount,
        fee: r.fee,
        to: r.receiver_username ? '@' + r.receiver_username : target.trim()
      };
      if (balance) balance = { ...balance, balance: r.sender_balance };
      haptic('success');
    } catch (e: any) {
      showAlert(e?.message ?? 'Не получилось');
      haptic('error');
    } finally {
      busy = false;
    }
  }
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Перевод</h1>

{#if balance}
  <div class="bal muted">
    Твой баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong>
  </div>
{/if}

<section class="card">
  <label class="lbl">
    <span class="muted small">Получатель</span>
    <input type="text" placeholder="@username или tg_id" bind:value={target} />
  </label>

  {#if people.length}
    <div class="people">
      {#each people.slice(0, 12) as p}
        <button
          class="chip"
          class:active={target === ('@' + (p.user.username ?? '')) ||
            target === String(p.user.tg_id)}
          on:click={() => pick(p.user)}
        >
          {p.user.username ? '@' + p.user.username : p.user.fullname ?? p.user.tg_id}
        </button>
      {/each}
    </div>
  {/if}

  <label class="lbl">
    <span class="muted small">Сумма (гривны)</span>
    <input type="number" min="1" step="10" bind:value={amount} />
  </label>
  <label class="lbl">
    <span class="muted small">Комментарий (опц.)</span>
    <input type="text" placeholder="за что" bind:value={note} />
  </label>

  <div class="summary muted small">
    Перевод: <strong style="color: var(--text)">{fmtCoins(amount)}</strong> ·
    комиссия 5%: <strong style="color: var(--text)">{fmtCoins(fee)}</strong> ·
    спишется: <strong style="color: var(--text)">{fmtCoins(total)}</strong>
  </div>

  <button
    class="play"
    disabled={busy || !target || amount < 1 || (balance ? total > balance.balance : false)}
    on:click={send}
  >
    {busy ? 'Отправляю…' : `Перевести ${fmtCoins(amount)}`}
  </button>

  {#if balance && total > balance.balance}
    <div class="danger small" style="margin-top: 8px">
      Не хватает: нужно {fmtCoins(total)} (с комиссией), у тебя {fmtCoins(balance.balance)}
    </div>
  {/if}

  {#if done}
    <div class="result success">
      Отправлено {fmtCoins(done.amount)} → {done.to} (комиссия {fmtCoins(done.fee)} в банк чата).
    </div>
  {/if}

  {#if err}
    <div class="danger" style="margin-top: 10px">{err}</div>
  {/if}
</section>

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .bal { font-size: 13px; margin-bottom: 12px; }
  .small { font-size: 12px; }
  .lbl { display: block; margin-bottom: 14px; }
  .lbl span { display: block; margin-bottom: 6px; }
  .lbl input {
    width: 100%;
    padding: 11px 12px;
    border: 1px solid var(--separator);
    border-radius: 9px;
    font-size: 16px;
    background: var(--bg);
    color: var(--text);
  }
  .people {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: -6px 0 14px;
  }
  .chip {
    padding: 6px 10px;
    border: 1px solid var(--separator);
    background: var(--bg);
    color: var(--text);
    border-radius: 999px;
    font-size: 12px;
    cursor: pointer;
    max-width: 140px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chip.active { border-color: var(--accent); background: var(--accent-soft); }
  .summary {
    margin-bottom: 12px;
    line-height: 1.5;
  }
  .play {
    width: 100%;
    padding: 14px;
    background: var(--accent);
    color: var(--accent-text);
    border: 0;
    border-radius: 10px;
    font-weight: 700;
    font-size: 15px;
    cursor: pointer;
  }
  .play:disabled { opacity: 0.5; }
  .result {
    margin-top: 14px;
    padding: 12px;
    border-radius: 10px;
    font-size: 14px;
  }
  .result.success { background: var(--positive-soft); color: var(--positive); }
</style>
