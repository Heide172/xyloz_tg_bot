<script lang="ts">
  import { onMount } from 'svelte';
  import BetInput from '$lib/BetInput.svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic } from '$lib/tg';
  import type { BalanceResponse, GameResult } from '$lib/types';

  // Стандартный европейский порядок чисел на колесе
  const WHEEL_ORDER = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
    10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
  ];
  const RED = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);

  function colorOf(n: number): 'red' | 'black' | 'green' {
    if (n === 0) return 'green';
    return RED.has(n) ? 'red' : 'black';
  }

  type BetType = 'color' | 'parity' | 'half' | 'dozen' | 'number';
  let balance: BalanceResponse | null = null;
  let amount = 100;
  let betType: BetType = 'color';
  let value: string = 'red';
  let busy = false;
  let last: GameResult | null = null;
  let err: string | null = null;

  let wheelDeg = 0;
  let spinning = false;

  onMount(async () => {
    try {
      balance = await api.balance();
    } catch (e: any) {
      err = e?.message;
    }
  });

  function setType(t: BetType) {
    betType = t;
    if (t === 'color') value = 'red';
    else if (t === 'parity') value = 'even';
    else if (t === 'half') value = 'low';
    else if (t === 'dozen') value = '1';
    else if (t === 'number') value = '0';
  }

  function spinTo(spin: number) {
    const idx = WHEEL_ORDER.indexOf(spin);
    const segDeg = 360 / WHEEL_ORDER.length;
    // несколько полных оборотов + позиция (минусом, т.к. крутим колесо против часовой)
    const target = 360 * 6 + idx * segDeg;
    wheelDeg = target;
  }

  async function play() {
    if (busy) return;
    err = null;
    busy = true;
    spinning = true;
    last = null;
    try {
      const r = await api.roulette(amount, betType, value);
      spinTo(r.details.spin);
      await new Promise((res) => setTimeout(res, 3300));
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
      spinning = false;
    }
  }

  $: search = typeof window !== 'undefined' ? window.location.search : '';
  $: segDeg = 360 / WHEEL_ORDER.length;
</script>

<a class="back" href={`/games${search}`}>← к играм</a>
<h1 class="h1">Roulette</h1>

{#if balance}
  <div class="bal muted">Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong></div>
{/if}

<section class="card">
  <div class="wheel-stage">
    <div class="pointer">▼</div>
    <div
      class="wheel"
      style="transform: rotate(-{wheelDeg}deg); transition: transform {spinning ? '3.2s' : '0s'} cubic-bezier(.2,.7,.3,1);"
    >
      {#each WHEEL_ORDER as n, i}
        {@const c = colorOf(n)}
        <div
          class="seg seg-{c}"
          style="transform: rotate({i * segDeg}deg) skewY(-{90 - segDeg}deg);"
        >
          <span style="transform: skewY({90 - segDeg}deg) rotate({segDeg / 2}deg);">{n}</span>
        </div>
      {/each}
      <div class="hub"></div>
    </div>
  </div>

  <div class="typetabs">
    {#each [['color', 'Цвет'], ['parity', 'Чёт/Нечёт'], ['half', '1-18/19-36'], ['dozen', 'Дюжина'], ['number', 'Номер']] as [t, label]}
      <button class="tab" class:active={betType === t} on:click={() => setType(t)}>{label}</button>
    {/each}
  </div>

  <div class="valuerow">
    {#if betType === 'color'}
      <button class="v red"   class:active={value === 'red'}   on:click={() => (value = 'red')}>Red ×2</button>
      <button class="v black" class:active={value === 'black'} on:click={() => (value = 'black')}>Black ×2</button>
    {:else if betType === 'parity'}
      <button class="v" class:active={value === 'even'} on:click={() => (value = 'even')}>Чёт ×2</button>
      <button class="v" class:active={value === 'odd'}  on:click={() => (value = 'odd')}>Нечёт ×2</button>
    {:else if betType === 'half'}
      <button class="v" class:active={value === 'low'}  on:click={() => (value = 'low')}>1–18 ×2</button>
      <button class="v" class:active={value === 'high'} on:click={() => (value = 'high')}>19–36 ×2</button>
    {:else if betType === 'dozen'}
      <button class="v" class:active={value === '1'} on:click={() => (value = '1')}>1–12 ×3</button>
      <button class="v" class:active={value === '2'} on:click={() => (value = '2')}>13–24 ×3</button>
      <button class="v" class:active={value === '3'} on:click={() => (value = '3')}>25–36 ×3</button>
    {:else}
      <input class="num-input" type="number" min="0" max="36" bind:value />
      <span class="muted small" style="align-self: center;">×36</span>
    {/if}
  </div>

  <div class="bet">
    <BetInput bind:amount balance={balance?.balance ?? null} disabled={busy} />
  </div>

  <button class="play" disabled={busy} on:click={play}>
    {busy ? 'Колесо крутится…' : `Поставить ${amount}`}
  </button>

  {#if err}
    <div class="danger" style="margin-top: 10px">{err}</div>
  {/if}

  {#if last && !busy}
    <div class="result" class:win={last.outcome === 'win'} class:lose={last.outcome === 'lose'}>
      Выпало <strong>{last.details.spin}</strong>
      <span class="dot dot-{last.details.color}"></span>
      ({last.details.color}).
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

  .wheel-stage {
    position: relative;
    width: 280px;
    height: 280px;
    margin: 0 auto 18px;
  }
  .pointer {
    position: absolute;
    top: -4px;
    left: 50%;
    transform: translateX(-50%);
    color: var(--accent);
    font-size: 22px;
    z-index: 2;
    line-height: 1;
  }
  .wheel {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    overflow: hidden;
    transform-origin: center;
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.25);
  }
  .seg {
    position: absolute;
    width: 50%;
    height: 50%;
    top: 0;
    right: 0;
    transform-origin: 0% 100%;
    overflow: hidden;
  }
  .seg span {
    position: absolute;
    bottom: 8px;
    right: 30%;
    transform-origin: center;
    font-size: 11px;
    color: white;
    font-weight: 700;
    pointer-events: none;
  }
  .seg-red   { background: #c1272d; }
  .seg-black { background: #1a1a1a; }
  .seg-green { background: #1e8a47; }
  .hub {
    position: absolute;
    top: 50%; left: 50%;
    width: 40px; height: 40px;
    background: var(--bg-elev);
    border: 2px solid var(--accent);
    border-radius: 50%;
    transform: translate(-50%, -50%);
  }

  .typetabs {
    display: flex; gap: 5px; flex-wrap: wrap;
    margin-bottom: 12px;
  }
  .tab {
    flex: 1 0 auto;
    padding: 8px 10px;
    border: 0; background: var(--bg-elev-2); color: var(--text-muted);
    border-radius: 8px; font-size: 12px; font-weight: 500; cursor: pointer;
  }
  .tab.active { background: var(--accent); color: var(--accent-text); }

  .valuerow {
    display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap;
  }
  .v {
    flex: 1 1 0;
    padding: 11px; border: 2px solid var(--separator); background: var(--bg);
    color: var(--text); border-radius: 10px; font-weight: 600; cursor: pointer;
    min-width: 30%;
  }
  .v.active { border-color: var(--accent); background: var(--accent-soft); }
  .v.red.active { border-color: #c1272d; background: rgba(193,39,45,0.18); }
  .v.black.active { border-color: #1a1a1a; background: rgba(0,0,0,0.16); }
  .num-input {
    flex: 1; padding: 11px 12px; border: 1px solid var(--separator);
    border-radius: 9px; font-size: 16px; background: var(--bg);
  }
  .small { font-size: 12px; }
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
  .dot {
    display: inline-block; width: 10px; height: 10px; border-radius: 50%;
    vertical-align: middle; margin: 0 4px;
  }
  .dot-red   { background: #c1272d; }
  .dot-black { background: #1a1a1a; }
  .dot-green { background: #1e8a47; }
</style>
