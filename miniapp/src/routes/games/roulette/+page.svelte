<script lang="ts">
  import { onMount } from 'svelte';
  import BetInput from '$lib/BetInput.svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic } from '$lib/tg';
  import type { BalanceResponse, GameResult } from '$lib/types';

  // Стандартный европейский порядок чисел на колесе (по часовой стрелке, начиная с 0)
  const WHEEL_ORDER = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
    10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
  ];
  const RED = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);
  const N = WHEEL_ORDER.length;
  const SEG = 360 / N;

  // Геометрия SVG-колеса
  const SIZE = 280;
  const CX = SIZE / 2;
  const CY = SIZE / 2;
  const R_OUT = 130;
  const R_IN = 90;
  const R_LBL = 110;

  function colorOf(n: number): 'red' | 'black' | 'green' {
    if (n === 0) return 'green';
    return RED.has(n) ? 'red' : 'black';
  }

  function polar(cx: number, cy: number, r: number, deg: number) {
    const rad = ((deg - 90) * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  function segmentPath(i: number): string {
    const start = i * SEG;
    const end = (i + 1) * SEG;
    const p1 = polar(CX, CY, R_OUT, start);
    const p2 = polar(CX, CY, R_OUT, end);
    const p3 = polar(CX, CY, R_IN, end);
    const p4 = polar(CX, CY, R_IN, start);
    const large = SEG > 180 ? 1 : 0;
    return [
      `M ${p1.x} ${p1.y}`,
      `A ${R_OUT} ${R_OUT} 0 ${large} 1 ${p2.x} ${p2.y}`,
      `L ${p3.x} ${p3.y}`,
      `A ${R_IN} ${R_IN} 0 ${large} 0 ${p4.x} ${p4.y}`,
      'Z'
    ].join(' ');
  }

  function labelPos(i: number) {
    const mid = i * SEG + SEG / 2;
    const p = polar(CX, CY, R_LBL, mid);
    return { x: p.x, y: p.y, rot: mid };
  }

  type BetType = 'color' | 'parity' | 'half' | 'dozen' | 'number';
  let balance: BalanceResponse | null = null;
  let amount = 100;
  let betType: BetType = 'color';
  let value: string = 'red';
  let busy = false;
  let last: GameResult | null = null;
  let err: string | null = null;

  let rotation = 0;
  let spinDuration = 0;

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

  async function play() {
    if (busy) return;
    err = null;
    busy = true;
    last = null;
    try {
      const r = await api.roulette(amount, betType, value);
      const idx = WHEEL_ORDER.indexOf(r.details.spin);
      // Сегмент idx занимает [idx*SEG .. (idx+1)*SEG], центр idx*SEG + SEG/2.
      // Поинтер указывает на угол 0 (12 часов). Если повернуть колесо
      // на (360 - center) — центр сегмента окажется напротив поинтера.
      const center = idx * SEG + SEG / 2;
      const targetAngle = 360 - center;
      const currentMod = ((rotation % 360) + 360) % 360;
      const delta = 360 * 6 + ((targetAngle - currentMod + 360) % 360);
      spinDuration = 4200;
      rotation = rotation + delta;
      await new Promise((res) => setTimeout(res, spinDuration + 100));
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
<h1 class="h1">Roulette</h1>

{#if balance}
  <div class="bal muted">
    Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong>
  </div>
{/if}

<section class="card">
  <div class="wheel-stage">
    <svg
      width={SIZE}
      height={SIZE}
      viewBox="0 0 {SIZE} {SIZE}"
      class="wheel"
      style="transform: rotate({rotation}deg); transition: transform {spinDuration}ms cubic-bezier(.17,.62,.18,1);"
    >
      <!-- Внешнее золотое кольцо -->
      <circle cx={CX} cy={CY} r={R_OUT + 8} fill="url(#rim)" />
      <circle cx={CX} cy={CY} r={R_OUT + 3} fill="#0a0a0c" />
      <defs>
        <radialGradient id="rim" cx="50%" cy="50%" r="50%">
          <stop offset="80%" stop-color="#f7d147" />
          <stop offset="100%" stop-color="#8a6510" />
        </radialGradient>
      </defs>
      {#each WHEEL_ORDER as n, i}
        {@const c = colorOf(n)}
        {@const lp = labelPos(i)}
        <path
          d={segmentPath(i)}
          fill={c === 'red' ? '#c1272d' : c === 'black' ? '#1c1c1e' : '#1e8a47'}
          stroke="#0a0a0c"
          stroke-width="0.5"
        />
        <text
          x={lp.x}
          y={lp.y}
          text-anchor="middle"
          dominant-baseline="central"
          fill="white"
          font-size="11"
          font-weight="700"
          transform={`rotate(${lp.rot} ${lp.x} ${lp.y})`}
        >
          {n}
        </text>
      {/each}
      <!-- Центральный диск -->
      <circle cx={CX} cy={CY} r={R_IN - 4} fill="url(#hub)" stroke="#2a2a2e" stroke-width="2" />
      <circle cx={CX} cy={CY} r="18" fill="#0a0a0c" />
      <defs>
        <radialGradient id="hub" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#3a3a3e" />
          <stop offset="100%" stop-color="#15151a" />
        </radialGradient>
      </defs>
    </svg>
    <!-- Шарик-указатель сверху (не вращается) -->
    <div class="pointer">
      <svg width="22" height="28" viewBox="0 0 22 28">
        <path d="M11 28 L0 8 A11 11 0 1 1 22 8 Z" fill="#f0f0f3" stroke="#1a1a1c" stroke-width="1.5" />
      </svg>
    </div>
  </div>

  <div class="typetabs">
    <button class="tab" class:active={betType === 'color'} on:click={() => setType('color')}>Цвет</button>
    <button class="tab" class:active={betType === 'parity'} on:click={() => setType('parity')}>Чёт/Нечёт</button>
    <button class="tab" class:active={betType === 'half'} on:click={() => setType('half')}>1-18/19-36</button>
    <button class="tab" class:active={betType === 'dozen'} on:click={() => setType('dozen')}>Дюжина</button>
    <button class="tab" class:active={betType === 'number'} on:click={() => setType('number')}>Номер</button>
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
    filter: drop-shadow(0 6px 20px rgba(0, 0, 0, 0.35));
  }
  .wheel { display: block; will-change: transform; }
  .pointer {
    position: absolute;
    top: -6px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 2;
    filter: drop-shadow(0 2px 3px rgba(0, 0, 0, 0.4));
    line-height: 0;
  }

  .typetabs {
    display: flex;
    gap: 5px;
    flex-wrap: wrap;
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
