<script lang="ts">
  import { onMount } from 'svelte';
  import BetInput from '$lib/BetInput.svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic } from '$lib/tg';
  import type { BalanceResponse, GameResult } from '$lib/types';

  const SYMBOL_LABEL: Record<string, string> = {
    cherry: 'C',
    lemon: 'L',
    bell: 'B',
    star: 'S',
    diamond: 'D'
  };

  let balance: BalanceResponse | null = null;
  let amount = 100;
  let busy = false;
  let last: GameResult | null = null;
  let err: string | null = null;

  let display: string[] = ['?', '?', '?'];
  let spinning = [false, false, false];

  onMount(async () => {
    try {
      balance = await api.balance();
    } catch (e: any) {
      err = e?.message;
    }
  });

  async function play() {
    if (busy) return;
    err = null;
    busy = true;
    spinning = [true, true, true];
    last = null;
    // фейковый "шум" катушек
    const noiseTimer = setInterval(() => {
      display = display.map(() =>
        SYMBOL_LABEL[['cherry', 'lemon', 'bell', 'star', 'diamond'][Math.floor(Math.random() * 5)]]
      );
    }, 70);
    try {
      const r = await api.slots(amount);
      clearInterval(noiseTimer);
      // последовательно "тормозим" катушки
      const reels = r.details.reels as string[];
      for (let i = 0; i < reels.length; i++) {
        await new Promise((res) => setTimeout(res, 250));
        display[i] = SYMBOL_LABEL[reels[i]] ?? reels[i][0].toUpperCase();
        spinning[i] = false;
        spinning = [...spinning];
        display = [...display];
      }
      last = r;
      balance = balance && {
        ...balance,
        balance: r.user_balance_after,
        bank: r.bank_after
      };
      haptic(r.outcome === 'win' ? 'success' : 'error');
    } catch (e: any) {
      clearInterval(noiseTimer);
      err = e?.message ?? 'Ошибка';
      haptic('error');
    } finally {
      busy = false;
      spinning = [false, false, false];
    }
  }

  $: search = typeof window !== 'undefined' ? window.location.search : '';
</script>

<a class="back" href={`/games${search}`}>← к играм</a>
<h1 class="h1">Slots</h1>

{#if balance}
  <div class="bal muted">Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong></div>
{/if}

<section class="card">
  <div class="reels">
    {#each display as d, i}
      <div class="reel" class:spinning={spinning[i]}>{d}</div>
    {/each}
  </div>

  <div class="paytable">
    <div class="pt-title muted">Выплаты (×bet)</div>
    <div class="pt-row"><span>3× <b>D</b></span> <span>50×</span></div>
    <div class="pt-row"><span>3× <b>S</b></span> <span>20×</span></div>
    <div class="pt-row"><span>3× <b>B</b></span> <span>10×</span></div>
    <div class="pt-row"><span>3× <b>L</b></span> <span>4×</span></div>
    <div class="pt-row"><span>3× <b>C</b></span> <span>2×</span></div>
    <div class="pt-row"><span>2× <b>C</b></span> <span>1×</span></div>
  </div>

  <div class="bet">
    <BetInput bind:amount balance={balance?.balance ?? null} disabled={busy} />
  </div>

  <button class="play" disabled={busy} on:click={play}>
    {busy ? 'Крутим…' : `Поставить ${amount}`}
  </button>

  {#if err}
    <div class="danger" style="margin-top: 10px">{err}</div>
  {/if}

  {#if last}
    <div class="result" class:win={last.outcome === 'win'} class:lose={last.outcome === 'lose'}>
      {#if last.outcome === 'win'}
        ×{last.details.multiplier}. Выигрыш +{fmtCoins(last.net)}.
      {:else}
        Не сложилось. −{fmtCoins(-last.net)}.
      {/if}
    </div>
  {/if}
</section>

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .bal { font-size: 13px; margin-bottom: 12px; }
  .reels {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
    margin-bottom: 16px;
  }
  .reel {
    aspect-ratio: 1; display: flex; align-items: center; justify-content: center;
    border-radius: 12px; background: var(--bg); border: 2px solid var(--separator);
    font-weight: 800; font-size: 42px; letter-spacing: -0.02em;
    box-shadow: inset 0 1px 4px rgba(0, 0, 0, 0.06);
  }
  .reel.spinning {
    border-color: var(--accent);
    color: var(--text-muted);
    animation: rumble 0.07s linear infinite alternate;
  }
  @keyframes rumble {
    from { transform: translateY(-1px); }
    to   { transform: translateY(1px); }
  }
  .paytable {
    background: var(--bg-elev-2); border-radius: 10px;
    padding: 10px 12px; margin-bottom: 14px;
    font-size: 13px; line-height: 1.6;
  }
  .pt-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
  .pt-row { display: flex; justify-content: space-between; }
  .pt-row b { font-family: ui-monospace, monospace; }
  .bet { margin-bottom: 14px; }
  .play {
    width: 100%; padding: 14px; background: var(--accent); color: var(--accent-text);
    border: 0; border-radius: 10px; font-weight: 700; font-size: 15px; cursor: pointer;
  }
  .play:disabled { opacity: 0.6; }
  .result {
    margin-top: 14px; padding: 12px; border-radius: 10px; font-size: 14px; text-align: center;
  }
  .result.win { background: var(--positive-soft); color: var(--positive); }
  .result.lose { background: rgba(204, 41, 41, 0.12); color: var(--destructive); }
</style>
