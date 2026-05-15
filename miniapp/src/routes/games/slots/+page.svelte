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
    cherry: '🍒',
    lemon: '🍋',
    bell: '🔔',
    star: '⭐',
    diamond: '💎',
    wild: '🃏',
    scatter: '✨'
  };

  // 10 линий — те же что на сервере (row idx на каждом из 5 барабанов)
  const LINES = [
    [1, 1, 1, 1, 1],
    [0, 0, 0, 0, 0],
    [2, 2, 2, 2, 2],
    [0, 1, 2, 1, 0],
    [2, 1, 0, 1, 2],
    [0, 0, 1, 0, 0],
    [2, 2, 1, 2, 2],
    [1, 2, 2, 2, 1],
    [1, 0, 0, 0, 1],
    [1, 1, 0, 1, 1]
  ];
  const LINE_COLORS = [
    '#ff5252', '#ffb300', '#2196f3', '#9c27b0', '#00bfa5',
    '#ff7043', '#26c6da', '#ec407a', '#7e57c2', '#66bb6a'
  ];

  const ROWS = 3;
  const REELS = 5;

  let balance: BalanceResponse | null = null;
  let amount = 100;
  let busy = false;
  let last: GameResult | null = null;
  let err: string | null = null;
  let imgOk: Record<Sym, boolean | null> = {
    cherry: null, lemon: null, bell: null, star: null,
    diamond: null, wild: null, scatter: null
  };

  // Текущая отображаемая сетка [reel][row]
  let grid: Sym[][] = Array.from({ length: REELS }, () =>
    ['cherry', 'lemon', 'bell'] as Sym[]
  );
  let reelSpinning = Array(REELS).fill(false);
  let activeLines: number[] = []; // подсвеченные выигрышные линии
  let winCells = new Set<string>(); // "reel-row" выигравших ячеек
  let displayWin = 0; // count-up
  let bigWin = false;

  // Фриспины
  let fsActive = false;
  let fsTotal = 0;
  let fsIndex = 0;
  let fsWinAccum = 0;

  // Web Audio (ленивая инициализация по первому клику)
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
    // мажорное арпеджио, для big-win длиннее и выше
    const base = [523.25, 659.25, 783.99, 1046.5]; // C5 E5 G5 C6
    base.forEach((f, i) => tone(f, i * 0.09, 0.25));
    if (big) {
      [1318.51, 1567.98, 2093.0].forEach((f, i) => tone(f, 0.4 + i * 0.1, 0.35, 0.2));
    }
  }
  function playSpinTick() {
    if (!audioCtx) return;
    tone(220, 0, 0.05, 0.06, 'square');
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

  function randSym(): Sym {
    return SYMBOLS[Math.floor(Math.random() * 5)]; // только обычные для "шума"
  }

  async function animateReels(finalGrid: Sym[][], winLines: any[]) {
    reelSpinning = Array(REELS).fill(true);
    activeLines = [];
    winCells = new Set();
    grid = grid.map(() => [randSym(), randSym(), randSym()]);

    const noise = setInterval(() => {
      for (let r = 0; r < REELS; r++) {
        if (reelSpinning[r]) {
          grid[r] = [randSym(), randSym(), randSym()];
        }
      }
      grid = [...grid];
    }, 80);

    // последовательная остановка барабанов
    for (let r = 0; r < REELS; r++) {
      await new Promise((res) => setTimeout(res, 280));
      grid[r] = finalGrid[r];
      reelSpinning[r] = false;
      reelSpinning = [...reelSpinning];
      grid = [...grid];
      playSpinTick();
      haptic('light');
    }
    clearInterval(noise);

    // подсветка выигрышных линий
    if (winLines.length) {
      activeLines = winLines.map((w) => w.line);
      const cells = new Set<string>();
      for (const w of winLines) {
        const ln = LINES[w.line];
        for (let r = 0; r < w.count; r++) {
          cells.add(`${r}-${ln[r]}`);
        }
      }
      winCells = cells;
    }
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

    try {
      const r = await api.slots(amount);
      const d = r.details;
      await animateReels(d.grid as Sym[][], (d.win_lines as any[]) ?? []);

      // Фриспины (если есть)
      const fs = (d.freespins as any[]) ?? [];
      if (fs.length > 0) {
        fsActive = true;
        fsTotal = fs.length;
        fsWinAccum = d.scatter_payout ?? 0;
        haptic('success');
        await new Promise((res) => setTimeout(res, 900));
        for (let i = 0; i < fs.length; i++) {
          fsIndex = i + 1;
          await animateReelsQuick(fs[i].grid as Sym[][], fs[i].lines ?? []);
          fsWinAccum += fs[i].win;
          if (fs[i].win > 0) playWinJingle(false);
          await new Promise((res) => setTimeout(res, 350));
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
      reelSpinning = Array(REELS).fill(false);
    }
  }

  // Быстрая версия для фриспинов (без долгой каскадной остановки)
  async function animateReelsQuick(finalGrid: Sym[][], winLines: any[]) {
    activeLines = [];
    winCells = new Set();
    for (let k = 0; k < 6; k++) {
      grid = grid.map(() => [randSym(), randSym(), randSym()]);
      await new Promise((res) => setTimeout(res, 55));
    }
    grid = finalGrid.map((c) => [...c]);
    if (winLines.length) {
      activeLines = winLines.map((w: any) => w.line);
      const cells = new Set<string>();
      for (const w of winLines) {
        const ln = LINES[w.line];
        for (let r = 0; r < w.count; r++) cells.add(`${r}-${ln[r]}`);
      }
      winCells = cells;
    }
  }

  $: search = typeof window !== 'undefined' ? window.location.search : '';
  function cellSym(reel: number, row: number): Sym {
    return grid[reel]?.[row] ?? 'cherry';
  }
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

    <div class="grid-wrap">
      <div class="grid">
        {#each Array(REELS) as _, reel}
          <div class="reel" class:spinning={reelSpinning[reel]}>
            {#each Array(ROWS) as _, row}
              {@const s = cellSym(reel, row)}
              <div class="cell" class:win={winCells.has(`${reel}-${row}`)} class:special={s === 'wild' || s === 'scatter'}>
                {#if imgOk[s]}
                  <img src={`/slots/${s}.png`} alt={s} draggable="false" />
                {:else}
                  <span class="emoji">{EMOJI[s]}</span>
                {/if}
              </div>
            {/each}
          </div>
        {/each}
      </div>

      <!-- Подсветка выигрышных линий -->
      {#if activeLines.length}
        <svg class="lines-overlay" viewBox="0 0 100 60" preserveAspectRatio="none">
          {#each activeLines as li}
            <polyline
              points={LINES[li]
                .map((rowIdx, reelIdx) => `${reelIdx * 20 + 10},${rowIdx * 20 + 10}`)
                .join(' ')}
              fill="none"
              stroke={LINE_COLORS[li]}
              stroke-width="1.4"
              stroke-linejoin="round"
              opacity="0.85"
            />
          {/each}
        </svg>
      {/if}
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
          · {last.details.scatter_count}× scatter → фриспины
        {/if}
      {:else}
        Не сложилось. −{fmtCoins(-last.net)}.
      {/if}
    </div>
  {/if}

  <div class="paytable">
    <div class="pt-title muted">5 барабанов · 3 ряда · 10 линий · 3+ слева</div>
    <div class="pt-grid">
      <span><span class="me">💎</span> 18/75/300</span>
      <span><span class="me">⭐</span> 12/38/135</span>
      <span><span class="me">🔔</span> 8/21/75</span>
      <span><span class="me">🍋</span> 3/9/27</span>
      <span><span class="me">🍒</span> 3/7/21</span>
      <span><span class="me">🃏</span> wild — замена</span>
      <span><span class="me">✨</span> scatter — фриспины</span>
    </div>
    <div class="muted pt-note">Выплаты ×ставка-на-линию (bet/10) за 3/4/5. 3+ ✨ → 8-15 фриспинов с ×2.</div>
  </div>

  <div class="bet">
    <BetInput bind:amount balance={balance?.balance ?? null} disabled={busy} />
  </div>

  <button class="play" disabled={busy} on:click={play}>
    {busy ? 'Крутим…' : `Spin · ${amount}`}
  </button>

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

  .grid-wrap { position: relative; }
  .grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 4px;
  }
  .reel {
    display: grid;
    grid-template-rows: repeat(3, 1fr);
    gap: 4px;
  }
  .reel.spinning { filter: blur(0.6px); }
  .cell {
    aspect-ratio: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #f7f4ee;
    border-radius: 7px;
    overflow: hidden;
    box-shadow: inset 0 2px 5px rgba(0, 0, 0, 0.18);
    transition: transform 0.12s ease;
  }
  .cell img { width: 100%; height: 100%; object-fit: cover; }
  .emoji { font-size: 30px; line-height: 1; }
  .cell.special { box-shadow: inset 0 0 0 2px #f7d147, inset 0 2px 5px rgba(0,0,0,0.18); }
  .cell.win {
    animation: cellpop 0.5s ease-in-out infinite alternate;
    box-shadow: inset 0 0 0 2px #ffd700, 0 0 10px rgba(255, 215, 0, 0.7);
    z-index: 1;
  }
  @keyframes cellpop {
    to { transform: scale(1.08); }
  }
  .reel.spinning .cell {
    animation: reelblur 0.12s linear infinite;
  }
  @keyframes reelblur {
    0% { transform: translateY(-2px); }
    100% { transform: translateY(2px); }
  }
  .lines-overlay {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
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
</style>
