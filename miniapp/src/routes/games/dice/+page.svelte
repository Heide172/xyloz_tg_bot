<script lang="ts">
  import { onMount } from 'svelte';
  import BetInput from '$lib/BetInput.svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic } from '$lib/tg';
  import type { BalanceResponse, GameResult } from '$lib/types';

  let balance: BalanceResponse | null = null;
  let amount = 100;
  let mode: 'over' | 'under' = 'over';
  let threshold = 50;
  let busy = false;
  let last: GameResult | null = null;
  let err: string | null = null;

  onMount(async () => {
    try {
      balance = await api.balance();
    } catch (e: any) {
      err = e?.message;
    }
  });

  $: winProb = mode === 'over' ? (100 - threshold) / 100 : (threshold - 1) / 100;
  $: multiplier = winProb > 0 ? Math.round((0.98 / winProb) * 100) / 100 : 0;
  $: potentialWin = Math.floor(amount * multiplier);

  async function play() {
    if (busy) return;
    err = null;
    busy = true;
    try {
      const r = await api.dice(amount, mode, threshold);
      last = r;
      balance = balance && {
        ...balance,
        balance: r.user_balance_after,
        bank: r.bank_after
      };
      haptic(r.outcome === 'win' ? 'success' : 'error');
    } catch (e: any) {
      err = e?.message ?? 'Ошибка';
      haptic('error');
    } finally {
      busy = false;
    }
  }

  $: search = typeof window !== 'undefined' ? window.location.search : '';
</script>

<a class="back" href={`/games${search}`}>← к играм</a>
<h1 class="h1">Dice</h1>

{#if balance}
  <div class="bal muted">Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong></div>
{/if}

<section class="card">
  <div class="roll-display" class:win={last?.outcome === 'win'} class:lose={last?.outcome === 'lose'}>
    {#if last}
      <span class="big">{last.details.roll}</span>
      <span class="muted">{last.outcome === 'win' ? 'выигрыш' : 'проигрыш'}</span>
    {:else}
      <span class="big muted">?</span>
      <span class="muted">бросок 1-100</span>
    {/if}
  </div>

  <div class="moderow">
    <button class="modebtn" class:active={mode === 'under'} on:click={() => (mode = 'under')}>
      Меньше
    </button>
    <button class="modebtn" class:active={mode === 'over'} on:click={() => (mode = 'over')}>
      Больше
    </button>
  </div>

  <label class="threshold">
    <div class="threshold-row">
      <span>Порог: <strong>{threshold}</strong></span>
      <span class="muted small">шанс {(winProb * 100).toFixed(0)}% · ×{multiplier}</span>
    </div>
    <input type="range" min="1" max="99" bind:value={threshold} />
  </label>

  <div class="bet">
    <BetInput bind:amount balance={balance?.balance ?? null} disabled={busy} />
    <div class="muted small" style="margin-top: 6px">
      При выигрыше: +{fmtCoins(potentialWin - amount)} (всего {fmtCoins(potentialWin)})
    </div>
  </div>

  <button class="play" disabled={busy} on:click={play}>
    {busy ? 'Бросаем…' : `Поставить ${amount}`}
  </button>

  {#if err}
    <div class="danger" style="margin-top: 10px">{err}</div>
  {/if}

  {#if last}
    <div class="result" class:winr={last.outcome === 'win'} class:loser={last.outcome === 'lose'}>
      Выпало <strong>{last.details.roll}</strong>.
      Ставка: {last.details.mode} {last.details.threshold} · ×{last.details.multiplier}.
      {#if last.outcome === 'win'}
        Выигрыш +{fmtCoins(last.net)}.
      {:else}
        Проигрыш {fmtCoins(-last.net)}.
      {/if}
    </div>
  {/if}
</section>

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .bal { font-size: 13px; margin-bottom: 12px; }
  .roll-display {
    display: flex; flex-direction: column; align-items: center;
    padding: 18px; border-radius: 12px; background: var(--bg-elev-2);
    margin-bottom: 14px;
  }
  .roll-display.win { background: var(--positive-soft); }
  .roll-display.lose { background: rgba(204, 41, 41, 0.12); }
  .big { font-size: 56px; font-weight: 700; letter-spacing: -0.02em; line-height: 1; }
  .moderow { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 14px; }
  .modebtn {
    padding: 11px; border: 2px solid var(--separator); background: var(--bg);
    color: var(--text); border-radius: 10px; font-weight: 600; cursor: pointer;
  }
  .modebtn.active { border-color: var(--accent); background: var(--accent-soft); }
  .threshold { display: block; margin-bottom: 14px; }
  .threshold-row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; font-size: 14px; }
  .threshold input[type="range"] { width: 100%; }
  .small { font-size: 12px; }
  .bet { margin-bottom: 14px; }
  .play {
    width: 100%; padding: 14px; background: var(--accent); color: var(--accent-text);
    border: 0; border-radius: 10px; font-weight: 700; font-size: 15px; cursor: pointer;
  }
  .play:disabled { opacity: 0.6; }
  .result {
    margin-top: 14px; padding: 12px; border-radius: 10px; font-size: 14px;
    background: var(--bg-elev-2);
  }
  .result.winr { background: var(--positive-soft); color: var(--positive); }
  .result.loser { background: rgba(204, 41, 41, 0.12); color: var(--destructive); }
</style>
