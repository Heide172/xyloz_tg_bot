<script lang="ts">
  import { onMount, tick } from 'svelte';
  import BetInput from '$lib/BetInput.svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic } from '$lib/tg';
  import type { BalanceResponse, GameResult } from '$lib/types';

  const SYMBOLS = ['cherry', 'lemon', 'bell', 'star', 'diamond', 'wild', 'scatter'] as const;
  type Sym = (typeof SYMBOLS)[number];
  const EMOJI: Record<Sym, string> = {
    cherry: '🍒', lemon: '🍋', bell: '🔔', star: '⭐',
    diamond: '💎', wild: '🃏', scatter: '✨'
  };
  const BASE_SYMS: Sym[] = ['cherry', 'lemon', 'bell', 'star', 'diamond'];

  const LINES = [
    [1, 1, 1, 1, 1], [0, 0, 0, 0, 0], [2, 2, 2, 2, 2],
    [0, 1, 2, 1, 0], [2, 1, 0, 1, 2],
    [0, 0, 1, 0, 0], [2, 2, 1, 2, 2],
    [1, 2, 2, 2, 1], [1, 0, 0, 0, 1], [1, 1, 0, 1, 1]
  ];

  const REELS = 5;
  const ROWS = 3;
  const CELL = 62; // px, фикс — нужно для математики прокрутки
  const GAP = 4;
  const STRIP_PAD = 24; // сколько случайных символов прокручиваем перед финалом

  let balance: BalanceResponse | null = null;
  let amount = 100;
  let busy = false;
  let last: GameResult | null = null;
  let err: string | null = null;
  let imgOk: Record<Sym, boolean | null> = {
    cherry: null, lemon: null, bell: null, star: null,
    diamond: null, wild: null, scatter: null
  };

  // Для каждого барабана — длинная лента символов + текущий offset (px) + transition
  let strips: Sym[][] = Array.from({ length: REELS }, () =>
    [...BASE_SYMS, ...BASE_SYMS, ...BASE_SYMS]
  );
  let offsets = Array(REELS).fill(0);
  let durations = Array(REELS).fill(0);

  let winCells = new Set<string>();
  let displayWin = 0;
  let bigWin = false;

  let fsActive = false;
  let fsTotal = 0;
  let fsIndex = 0;
  let fsWinAccum = 0;

  let gridWrapEl: HTMLDivElement;

  // ---- Web Audio ----
  let audioCtx: AudioContext | null = null;
  function ensureAudio() {
    if (!audioCtx) {
      try {
        audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      } catch {
        audioCtx = null;
      }
    }
  }
  function tone(freq: number, start: number, dur: number, gain = 0.18, type: OscillatorType = 'triangle') {
    if (!audioCtx) return;
    const t0 = audioCtx.currentTime + start;
    const osc = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(gain, t0 + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(g).connect(audioCtx.destination);
    osc.start(t0);
    osc.stop(t0 + dur + 0.05);
  }
  function playWinJingle(big: boolean) {
    if (!audioCtx) return;
    [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => tone(f, i * 0.09, 0.25));
    if (big) [1318.51, 1567.98, 2093.0].forEach((f, i) => tone(f, 0.4 + i * 0.1, 0.35, 0.2));
  }
  function reelStopTick() {
    if (!audioCtx) return;
    tone(180, 0, 0.06, 0.07, 'square');
  }

  onMount(async () => {
    try {
      balance = await api.balance();
    } catch (e: any) {
      err = e?.message;
    }
    for (const s of SYMBOLS) {
      const img = new Image();
      img.onload = () => (imgOk[s] = true);
      img.onerror = () => (imgOk[s] = false);
      img.src = `/slots/${s}.png`;
    }
  });

  function rnd(): Sym {
    return BASE_SYMS[Math.floor(Math.random() * BASE_SYMS.length)];
  }

  // Строим ленту: [случайный шум...] + [3 финальных символа этого барабана внизу]
  function buildStrip(finalCol: Sym[]): Sym[] {
    const noise: Sym[] = [];
    for (let i = 0; i < STRIP_PAD; i++) noise.push(rnd());
    return [...noise, ...finalCol]; // длина STRIP_PAD + 3
  }

  // Финальная позиция: показать последние 3 ячейки ленты в окне
  function finalOffset(strip: Sym[]): number {
    // окно показывает 3 ячейки; нужно сдвинуть так, чтобы последние 3 были видны
    const totalH = strip.length * CELL + (strip.length - 1) * GAP;
    const windowH = ROWS * CELL + (ROWS - 1) * GAP;
    return totalH - windowH;
  }

  async function spinReels(finalGrid: Sym[][]) {
    // подготовить ленты
    strips = finalGrid.map((col) => buildStrip(col));
    durations = Array(REELS).fill(0);
    offsets = Array(REELS).fill(0);
    await tick();
    // форс reflow чтобы reset применился до анимации
    void gridWrapEl?.offsetHeight;

    // запускаем прокрутку всех, останавливаем каскадом
    for (let r = 0; r < REELS; r++) {
      durations[r] = 1400 + r * 320;
      offsets[r] = finalOffset(strips[r]);
    }
    durations = [...durations];
    offsets = [...offsets];

    // ждать остановки каждого барабана по очереди (для звука/хаптика)
    for (let r = 0; r < REELS; r++) {
      const wait = r === 0 ? 1400 : 320;
      await new Promise((res) => setTimeout(res, wait));
      reelStopTick();
      haptic('light');
    }
  }

  function computeLines(winLines: any[]) {
    // Выделяем сами выигрышные ячейки (без линий) — приподнимаем + glow.
    const cells = new Set<string>();
    for (const w of winLines) {
      const ln = LINES[w.line];
      for (let r = 0; r < w.count; r++) cells.add(`${r}-${ln[r]}`);
    }
    winCells = cells;
  }

  async function countUp(target: number) {
    if (target <= 0) {
      displayWin = 0;
      return;
    }
    const steps = 24;
    for (let i = 1; i <= steps; i++) {
      displayWin = Math.round((target * i) / steps);
      await new Promise((res) => setTimeout(res, 22));
    }
    displayWin = target;
  }

  async function play() {
    if (busy) return;
    ensureAudio();
    if (audioCtx?.state === 'suspended') audioCtx.resume();
    err = null;
    busy = true;
    last = null;
    displayWin = 0;
    bigWin = false;
    fsActive = false;
    winCells = new Set();

    try {
      const r = await api.slots(amount);
      const d = r.details;
      await spinReels(d.grid as Sym[][]);
      await new Promise((res) => setTimeout(res, 150)); // дать transition устаканиться
      computeLines((d.win_lines as any[]) ?? []);

      const fs = (d.freespins as any[]) ?? [];
      if (fs.length > 0) {
        fsActive = true;
        fsTotal = fs.length;
        fsWinAccum = d.scatter_payout ?? 0;
        haptic('success');
        await new Promise((res) => setTimeout(res, 900));
        for (let i = 0; i < fs.length; i++) {
          fsIndex = i + 1;
          winCells = new Set();
          await spinReelsQuick(fs[i].grid as Sym[][]);
          await new Promise((res) => setTimeout(res, 120));
          computeLines(fs[i].lines ?? []);
          fsWinAccum += fs[i].win;
          if (fs[i].win > 0) playWinJingle(false);
          await new Promise((res) => setTimeout(res, 450));
        }
        await new Promise((res) => setTimeout(res, 600));
        fsActive = false;
      }

      last = r;
      balance = balance && {
        ...balance,
        balance: r.user_balance_after,
        bank: r.bank_after
      };
      bigWin = r.payout >= amount * 10;
      if (r.outcome === 'win') {
        playWinJingle(bigWin);
        haptic(bigWin ? 'success' : 'light');
        await countUp(r.payout);
      } else {
        haptic('error');
      }
    } catch (e: any) {
      err = e?.message ?? 'Ошибка';
      haptic('error');
    } finally {
      busy = false;
    }
  }

  // ---- автоспин ----
  let autoRunning = false;
  let autoLeft = 0;
  let autoInfinite = false;

  async function startAuto(n: number | 'inf') {
    if (autoRunning || busy) return;
    autoInfinite = n === 'inf';
    autoLeft = autoInfinite ? Infinity : (n as number);
    autoRunning = true;
    ensureAudio();
    if (audioCtx?.state === 'suspended') audioCtx.resume();
    while (autoRunning && autoLeft > 0) {
      if (!balance || balance.balance < amount) {
        err = 'Автоспин остановлен: недостаточно баланса';
        break;
      }
      await play();
      if (!autoRunning) break;
      autoLeft -= 1;
      if (autoLeft <= 0) break;
      await new Promise((res) => setTimeout(res, 650));
    }
    autoRunning = false;
    autoInfinite = false;
    autoLeft = 0;
  }

  function stopAuto() {
    autoRunning = false;
    autoLeft = 0;
    autoInfinite = false;
  }

  async function spinReelsQuick(finalGrid: Sym[][]) {
    strips = finalGrid.map((col) => buildStrip(col));
    durations = Array(REELS).fill(0);
    offsets = Array(REELS).fill(0);
    await tick();
    void gridWrapEl?.offsetHeight;
    for (let r = 0; r < REELS; r++) {
      durations[r] = 650 + r * 120;
      offsets[r] = finalOffset(strips[r]);
    }
    durations = [...durations];
    offsets = [...offsets];
    await new Promise((res) => setTimeout(res, 650 + (REELS - 1) * 120 + 80));
  }

  $: search = typeof window !== 'undefined' ? window.location.search : '';
  $: windowH = ROWS * CELL + (ROWS - 1) * GAP;
</script>

<a class="back" href={`/games${search}`}>← к играм</a>
<h1 class="h1">Slots</h1>

{#if balance}
  <div class="bal muted">
    Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong>
  </div>
{/if}

<section class="card">
  <div class="machine" class:bigwin={bigWin}>
    {#if fsActive}
      <div class="fs-banner">
        <span class="fs-title">FREE SPINS</span>
        <span class="fs-count">{fsIndex} / {fsTotal}</span>
        <span class="fs-win">+{fmtCoins(fsWinAccum)}</span>
      </div>
    {/if}

    <div
      class="grid-wrap"
      class:has-wins={winCells.size > 0}
      bind:this={gridWrapEl}
      style="height: {windowH}px"
    >
      <div class="reels" style="gap: {GAP}px">
        {#each strips as strip, reel}
          <div class="reel" style="width: {CELL}px; height: {windowH}px">
            <div
              class="strip"
              style="transform: translateY(-{offsets[reel]}px);
                     transition: transform {durations[reel]}ms cubic-bezier(.15,.45,.2,1);
                     gap: {GAP}px"
            >
              {#each strip as s, idx}
                {@const isFinal = idx >= strip.length - ROWS}
                {@const row = idx - (strip.length - ROWS)}
                <div
                  class="cell"
                  data-cell={isFinal ? `${reel}-${row}` : null}
                  class:win={isFinal && winCells.has(`${reel}-${row}`)}
                  class:special={s === 'wild' || s === 'scatter'}
                  style="width: {CELL}px; height: {CELL}px"
                >
                  {#if imgOk[s]}
                    <img src={`/slots/${s}.png`} alt={s} draggable="false" />
                  {:else}
                    <span class="emoji">{EMOJI[s]}</span>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    </div>
  </div>

  {#if last && !busy}
    <div
      class="result"
      class:win={last.outcome === 'win'}
      class:lose={last.outcome === 'lose'}
      class:big={bigWin}
    >
      {#if last.outcome === 'win'}
        {bigWin ? 'BIG WIN! ' : ''}+{fmtCoins(displayWin)}
        {#if last.details.scatter_count >= 3}
          · {last.details.scatter_count}× scatter
        {/if}
      {:else}
        Не сложилось. −{fmtCoins(-last.net)}.
      {/if}
    </div>
  {/if}

  <div class="paytable">
    <div class="pt-title muted">5 барабанов · 3 ряда · 10 линий · 3+ слева</div>
    <div class="pt-grid">
      <span><span class="me">💎</span> 15/60/240</span>
      <span><span class="me">⭐</span> 10/30/108</span>
      <span><span class="me">🔔</span> 6/17/60</span>
      <span><span class="me">🍋</span> 2/8/22</span>
      <span><span class="me">🍒</span> 2/6/17</span>
      <span><span class="me">🃏</span> wild — замена</span>
      <span><span class="me">✨</span> scatter — фриспины</span>
    </div>
    <div class="muted pt-note">×ставка-на-линию (bet/10) за 3/4/5. 3+ ✨ → 6-12 фриспинов ×2 (≈раз в 18 спинов).</div>
  </div>

  <div class="bet">
    <BetInput bind:amount balance={balance?.balance ?? null} disabled={busy} />
  </div>

  <button class="play" disabled={busy || autoRunning} on:click={play}>
    {busy && !autoRunning ? 'Крутим…' : `Spin · ${amount}`}
  </button>

  <div class="auto-row">
    {#if autoRunning}
      <button class="auto-stop" on:click={stopAuto}>
        Стоп · авто {autoInfinite ? '∞' : autoLeft}
      </button>
    {:else}
      <span class="auto-label muted">Авто:</span>
      {#each [10, 25, 50] as n}
        <button class="auto-btn" disabled={busy} on:click={() => startAuto(n)}>×{n}</button>
      {/each}
      <button class="auto-btn" disabled={busy} on:click={() => startAuto('inf')}>∞</button>
    {/if}
  </div>

  {#if err}
    <div class="danger" style="margin-top: 10px">{err}</div>
  {/if}
</section>

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .bal { font-size: 13px; margin-bottom: 12px; }

  .machine {
    position: relative;
    background: linear-gradient(180deg, #2a2a2e, #15151a);
    border: 3px solid;
    border-color: #d4a020 #8a6510 #5b3e00 #d4a020;
    border-radius: 14px;
    padding: 12px;
    margin-bottom: 14px;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4);
    transition: box-shadow 0.3s ease;
  }
  .machine.bigwin {
    box-shadow: 0 0 28px rgba(247, 209, 71, 0.75), 0 6px 16px rgba(0, 0, 0, 0.4);
    animation: bigpulse 0.6s ease-in-out 3;
  }
  @keyframes bigpulse {
    50% { box-shadow: 0 0 44px rgba(247, 209, 71, 0.95); }
  }

  .fs-banner {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: linear-gradient(90deg, #6a4cff, #b14cff);
    color: #fff;
    border-radius: 8px;
    padding: 6px 12px;
    margin-bottom: 8px;
    font-weight: 700;
    font-size: 13px;
  }
  .fs-title { letter-spacing: 0.08em; }
  .fs-win { font-variant-numeric: tabular-nums; }

  .grid-wrap {
    position: relative;
    overflow: hidden;
    border-radius: 8px;
    margin: 0 auto;
    width: fit-content;
  }
  .reels {
    display: flex;
  }
  .reel {
    overflow: hidden;
    background: #f7f4ee;
    border-radius: 7px;
    box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.2);
  }
  .strip {
    display: flex;
    flex-direction: column;
    will-change: transform;
  }
  .cell {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
  .cell img { width: 100%; height: 100%; object-fit: cover; }
  .emoji { font-size: 34px; line-height: 1; }
  .cell.special {
    box-shadow: inset 0 0 0 3px #f7d147;
    border-radius: 6px;
  }
  .cell.win {
    animation: cellpop 0.7s ease-in-out infinite alternate;
    border-radius: 8px;
    z-index: 2;
    position: relative;
  }
  /* Приподнимаем и подсвечиваем выигрышный блок */
  @keyframes cellpop {
    from {
      transform: translateY(0) scale(1);
      box-shadow: inset 0 0 0 3px #ffd700, 0 0 10px rgba(255, 215, 0, 0.6);
    }
    to {
      transform: translateY(-7px) scale(1.13);
      box-shadow:
        inset 0 0 0 3px #fff3a0,
        0 0 22px rgba(255, 215, 0, 0.95),
        0 10px 16px rgba(0, 0, 0, 0.45);
    }
  }
  /* Затемняем НЕ выигрышные ячейки чтобы выигрышные выделялись */
  .grid-wrap.has-wins .cell:not(.win) {
    filter: brightness(0.42) saturate(0.7);
    transition: filter 0.25s ease;
  }

  .result {
    margin: 12px 0;
    padding: 12px;
    border-radius: 10px;
    font-size: 15px;
    text-align: center;
    font-weight: 700;
  }
  .result.win { background: var(--positive-soft); color: var(--positive); }
  .result.lose { background: rgba(204, 41, 41, 0.12); color: var(--destructive); }
  .result.big {
    background: linear-gradient(90deg, #f7d147, #ffb300);
    color: #5b3e00;
    font-size: 18px;
    animation: bigpulse 0.5s ease-in-out 4;
  }

  .paytable {
    background: var(--bg-elev-2);
    border-radius: 10px;
    padding: 10px 12px;
    margin-bottom: 14px;
    font-size: 12px;
  }
  .pt-title {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 6px;
  }
  .pt-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 3px 10px;
  }
  .me { font-size: 14px; margin-right: 3px; }
  .pt-note { margin-top: 6px; font-size: 11px; line-height: 1.4; }

  .bet { margin-bottom: 14px; }
  .play {
    width: 100%; padding: 14px; background: var(--accent); color: var(--accent-text);
    border: 0; border-radius: 10px; font-weight: 700; font-size: 15px; cursor: pointer;
  }
  .play:disabled { opacity: 0.6; }

  .auto-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .auto-label { font-size: 13px; }
  .auto-btn {
    flex: 1;
    min-width: 48px;
    padding: 9px;
    background: var(--bg-elev-2);
    color: var(--text);
    border: 0;
    border-radius: 8px;
    font-weight: 600;
    font-size: 13px;
    cursor: pointer;
  }
  .auto-btn:disabled { opacity: 0.5; }
  .auto-stop {
    width: 100%;
    padding: 11px;
    background: var(--destructive);
    color: #fff;
    border: 0;
    border-radius: 8px;
    font-weight: 700;
    font-size: 14px;
    cursor: pointer;
  }
</style>
