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
  let flipping = false;
  let err: string | null = null;

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
    flipping = true;
    try {
      const result = await api.coinflip(amount, pick);
      // короткая "анимация" перед показом
      await new Promise((r) => setTimeout(r, 700));
      last = result;
      balance = balance && {
        ...balance,
        balance: result.user_balance_after,
        bank: result.bank_after
      };
      haptic(result.outcome === 'win' ? 'success' : 'error');
    } catch (e: any) {
      err = e?.message ?? 'Ошибка';
      haptic('error');
    } finally {
      busy = false;
      flipping = false;
    }
  }

  $: search = typeof window !== 'undefined' ? window.location.search : '';
</script>

<a class="back" href={`/games${search}`}>← к играм</a>
<h1 class="h1">Coinflip</h1>

{#if balance}
  <div class="bal muted">Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong></div>
{/if}

<section class="card">
  <div class="coin-stage">
    <div
      class="coin"
      class:flipping
      class:heads={!flipping && last && last.details.result === 'heads'}
      class:tails={!flipping && last && last.details.result === 'tails'}
    >
      <div class="face front">H</div>
      <div class="face back">T</div>
    </div>
  </div>

  <div class="pickrow">
    <button class="pickbtn" class:active={pick === 'heads'} on:click={() => (pick = 'heads')}>
      Орёл (H)
    </button>
    <button class="pickbtn" class:active={pick === 'tails'} on:click={() => (pick = 'tails')}>
      Решка (T)
    </button>
  </div>

  <div class="bet">
    <BetInput bind:amount balance={balance?.balance ?? null} disabled={busy} />
  </div>

  <button class="play" disabled={busy} on:click={play}>
    {busy ? 'Бросаем…' : `Поставить ${amount}`}
  </button>

  {#if err}
    <div class="danger" style="margin-top: 10px">{err}</div>
  {/if}

  {#if last}
    <div class="result" class:win={last.outcome === 'win'} class:lose={last.outcome === 'lose'}>
      {#if last.outcome === 'win'}
        Выпало <strong>{last.details.result}</strong>. Выигрыш +{fmtCoins(last.net)}.
      {:else}
        Выпало <strong>{last.details.result}</strong>. Проигрыш {fmtCoins(-last.net)}.
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
    height: 140px;
    perspective: 800px;
    margin-bottom: 18px;
  }
  .coin {
    width: 110px;
    height: 110px;
    position: relative;
    transform-style: preserve-3d;
    transition: transform 0.7s cubic-bezier(.2,.7,.3,1);
  }
  .coin.flipping {
    animation: spin 0.7s linear;
  }
  .coin.heads {
    transform: rotateY(0deg);
  }
  .coin.tails {
    transform: rotateY(180deg);
  }
  @keyframes spin {
    from { transform: rotateY(0); }
    to   { transform: rotateY(1080deg); }
  }
  .face {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 48px;
    font-weight: 700;
    background: linear-gradient(135deg, #f7d147, #d4a020);
    color: #5b3e00;
    box-shadow: 0 4px 14px rgba(0,0,0,0.3);
  }
  .face.back {
    transform: rotateY(180deg);
    background: linear-gradient(135deg, #d3d6db, #8a8d93);
    color: #2f3033;
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
  }
  .pickbtn.active {
    border-color: var(--accent);
    background: var(--accent-soft);
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
