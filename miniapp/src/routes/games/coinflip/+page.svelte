<script lang="ts">
  import { onMount } from 'svelte';
  import BetInput from '$lib/BetInput.svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic } from '$lib/tg';
  import type { BalanceResponse, GameResult } from '$lib/types';

  let balance: BalanceResponse | null = null;
  let amount = 100;
  let pick: 'heads' | 'tails' = 'heads';
  let busy = false;
  let last: GameResult | null = null;
  let err: string | null = null;

  // Накопительный угол вращения. Reactivity — Svelte ставит transition.
  let rotation = 0;
  let spinDuration = 0;

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
    last = null;
    try {
      const r = await api.coinflip(amount, pick);
      // финальный поворот: 0 — orёл (front), 180 — решка (back)
      const finalHalf = r.details.result === 'heads' ? 0 : 180;
      const currentMod = ((rotation % 360) + 360) % 360;
      // 6 полных оборотов + поправка до целевого положения
      const delta = 360 * 6 + ((finalHalf - currentMod + 360) % 360);
      spinDuration = 2200;
      rotation = rotation + delta;
      await new Promise((res) => setTimeout(res, spinDuration));
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
<h1 class="h1">Coinflip</h1>

{#if balance}
  <div class="bal muted">
    Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong>
  </div>
{/if}

<section class="card">
  <div class="coin-stage">
    <div
      class="coin"
      style="transform: rotateY({rotation}deg); transition: transform {spinDuration}ms cubic-bezier(.18,.72,.26,1);"
    >
      <div class="face heads">
        <div class="rim"></div>
        <div class="emblem">H</div>
        <div class="label">HEADS</div>
      </div>
      <div class="face tails">
        <div class="rim"></div>
        <div class="emblem">T</div>
        <div class="label">TAILS</div>
      </div>
      <!-- псевдо-«ребро» через box-shadow на родителе -->
    </div>
  </div>

  <div class="pickrow">
    <button class="pickbtn heads-btn" class:active={pick === 'heads'} on:click={() => (pick = 'heads')} disabled={busy}>
      Орёл (H) · ×1.98
    </button>
    <button class="pickbtn tails-btn" class:active={pick === 'tails'} on:click={() => (pick = 'tails')} disabled={busy}>
      Решка (T) · ×1.98
    </button>
  </div>

  <div class="bet">
    <BetInput bind:amount balance={balance?.balance ?? null} disabled={busy} />
  </div>

  <button class="play" disabled={busy} on:click={play}>
    {busy ? 'В воздухе…' : `Бросить ${amount}`}
  </button>

  {#if err}
    <div class="danger" style="margin-top: 10px">{err}</div>
  {/if}

  {#if last && !busy}
    <div class="result" class:win={last.outcome === 'win'} class:lose={last.outcome === 'lose'}>
      Выпало <strong>{last.details.result === 'heads' ? 'орёл' : 'решка'}</strong>.
      {#if last.outcome === 'win'}
        Выигрыш +{fmtCoins(last.net)}.
      {:else}
        Проигрыш {fmtCoins(-last.net)}.
      {/if}
    </div>
  {/if}
</section>

<style>
  .back {
    display: inline-block;
    margin-bottom: 8px;
    font-size: 14px;
    color: var(--text-muted);
  }
  .bal {
    font-size: 13px;
    margin-bottom: 12px;
  }
  .coin-stage {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 180px;
    perspective: 1000px;
    margin-bottom: 22px;
  }
  .coin {
    width: 140px;
    height: 140px;
    position: relative;
    transform-style: preserve-3d;
    will-change: transform;
    /* объёмный обод */
    filter: drop-shadow(0 8px 12px rgba(0, 0, 0, 0.35));
  }
  .face {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    backface-visibility: hidden;
    -webkit-backface-visibility: hidden;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    overflow: hidden;
  }
  .face.heads {
    background: radial-gradient(circle at 35% 30%, #fde58a 0%, #d4a020 50%, #8a6510 100%);
    color: #4a2f00;
    box-shadow:
      inset -4px -4px 12px rgba(0, 0, 0, 0.35),
      inset 4px 4px 14px rgba(255, 255, 255, 0.45);
  }
  .face.tails {
    background: radial-gradient(circle at 35% 30%, #f0f0f3 0%, #b5b8bf 50%, #6a6d75 100%);
    color: #1f2024;
    box-shadow:
      inset -4px -4px 12px rgba(0, 0, 0, 0.35),
      inset 4px 4px 14px rgba(255, 255, 255, 0.55);
    transform: rotateY(180deg);
  }
  .rim {
    position: absolute;
    inset: 4px;
    border-radius: 50%;
    border: 2px dashed rgba(0, 0, 0, 0.25);
    pointer-events: none;
  }
  .emblem {
    font-size: 56px;
    font-weight: 900;
    font-family: 'Times New Roman', serif;
    line-height: 1;
    letter-spacing: -0.02em;
    text-shadow: 0 1px 0 rgba(255, 255, 255, 0.5), 0 -1px 0 rgba(0, 0, 0, 0.3);
  }
  .label {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.18em;
    opacity: 0.65;
  }

  .pickrow {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-bottom: 14px;
  }
  .pickbtn {
    padding: 12px;
    border: 2px solid var(--separator);
    background: var(--bg);
    color: var(--text);
    border-radius: 10px;
    font-weight: 600;
    cursor: pointer;
    font-size: 13px;
  }
  .pickbtn.active.heads-btn {
    border-color: #d4a020;
    background: rgba(212, 160, 32, 0.15);
  }
  .pickbtn.active.tails-btn {
    border-color: #8a8d93;
    background: rgba(138, 141, 147, 0.15);
  }
  .pickbtn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  .bet {
    margin-bottom: 14px;
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
  .play:disabled {
    opacity: 0.6;
  }
  .result {
    margin-top: 14px;
    padding: 12px;
    border-radius: 10px;
    font-size: 14px;
    text-align: center;
  }
  .result.win {
    background: var(--positive-soft);
    color: var(--positive);
  }
  .result.lose {
    background: rgba(204, 41, 41, 0.12);
    color: var(--destructive);
  }
</style>
