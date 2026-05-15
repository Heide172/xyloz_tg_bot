<script lang="ts">
  import { onMount, tick } from 'svelte';
  import BetInput from '$lib/BetInput.svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic } from '$lib/tg';
  import type { BalanceResponse, GameResult } from '$lib/types';

  // Символы и их визуальное представление. Если в /slots/<id>.png лежит
  // картинка — она будет загружена и заменит эмодзи (см. <img onerror>).
  const SYMBOLS = ['cherry', 'lemon', 'bell', 'star', 'diamond'] as const;
  type Sym = (typeof SYMBOLS)[number];
  const EMOJI: Record<Sym, string> = {
    cherry: '🍒',
    lemon: '🍋',
    bell: '🔔',
    star: '⭐',
    diamond: '💎'
  };

  const CELL_H = 100; // высота "ячейки" катушки в px
  const STRIP_LEN = 36; // сколько символов в полоске (длиннее = «дольше крутит»)

  let balance: BalanceResponse | null = null;
  let amount = 100;
  let busy = false;
  let last: GameResult | null = null;
  let err: string | null = null;

  // По катушке: предзаготовленная полоска символов + текущий offset в px.
  let strips: Sym[][] = [
    buildStrip('cherry'),
    buildStrip('lemon'),
    buildStrip('bell')
  ];
  let offsets = [0, 0, 0];
  let durations = [0, 0, 0];
  let imgOk: Record<Sym, boolean | null> = { cherry: null, lemon: null, bell: null, star: null, diamond: null };

  function buildStrip(final: Sym): Sym[] {
    // случайный шум + последний символ = final (он окажется в "окне" после спина)
    const arr: Sym[] = [];
    for (let i = 0; i < STRIP_LEN - 1; i++) {
      arr.push(SYMBOLS[Math.floor(Math.random() * SYMBOLS.length)]);
    }
    arr.push(final);
    return arr;
  }

  onMount(async () => {
    try {
      balance = await api.balance();
    } catch (e: any) {
      err = e?.message;
    }
    // Проверим есть ли картинки в static/slots/
    for (const s of SYMBOLS) {
      const img = new Image();
      img.onload = () => (imgOk[s] = true);
      img.onerror = () => (imgOk[s] = false);
      img.src = `/slots/${s}.png`;
    }
  });

  async function play() {
    if (busy) return;
    err = null;
    busy = true;
    last = null;

    // 1) Сброс к нулю (моментально, без transition) перед новым спином
    durations = [0, 0, 0];
    offsets = [0, 0, 0];
    await tick();
    // forced reflow чтобы браузер применил reset перед новой transition
    void (document.body && document.body.offsetHeight);

    try {
      const r = await api.slots(amount);
      const reels: Sym[] = (r.details.reels as string[]).map((x) => x as Sym);
      // Перестроим полоски так, чтобы финальный символ был в нужной позиции.
      strips = reels.map((sym) => buildStrip(sym));
      // Целевой offset: STRIP_LEN-1 ячейка скроллится наверх
      const targetOffset = (STRIP_LEN - 1) * CELL_H;
      // Катушки тормозят последовательно
      durations = [2200, 2700, 3200];
      offsets = [targetOffset, targetOffset, targetOffset];

      // Тикающий звук-плейсхолдер — haptic для каждой остановившейся
      await new Promise((res) => setTimeout(res, 2200));
      haptic('light');
      await new Promise((res) => setTimeout(res, 500));
      haptic('light');
      await new Promise((res) => setTimeout(res, 500));
      haptic(r.outcome === 'win' ? 'success' : 'error');

      last = r;
      balance = balance && {
        ...balance,
        balance: r.user_balance_after,
        bank: r.bank_after
      };
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
<h1 class="h1">Slots</h1>

{#if balance}
  <div class="bal muted">
    Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong>
  </div>
{/if}

<section class="card">
  <div class="machine">
    <div class="reels">
      {#each strips as strip, ri}
        <div class="reel">
          <div
            class="strip"
            style="transform: translateY(-{offsets[ri]}px); transition: transform {durations[ri]}ms cubic-bezier(.15,.55,.2,1);"
          >
            {#each strip as s}
              <div class="cell">
                {#if imgOk[s]}
                  <img src={`/slots/${s}.png`} alt={s} />
                {:else}
                  <span class="emoji">{EMOJI[s]}</span>
                {/if}
              </div>
            {/each}
          </div>
          <div class="window-overlay top"></div>
          <div class="window-overlay bottom"></div>
          <div class="payline" />
        </div>
      {/each}
    </div>
  </div>

  <div class="paytable">
    <div class="pt-title muted">Выплаты (×bet)</div>
    <div class="pt-row"><span><span class="mini-emoji">💎</span><span class="mini-emoji">💎</span><span class="mini-emoji">💎</span></span><span>650×</span></div>
    <div class="pt-row"><span><span class="mini-emoji">⭐</span><span class="mini-emoji">⭐</span><span class="mini-emoji">⭐</span></span><span>85×</span></div>
    <div class="pt-row"><span><span class="mini-emoji">🔔</span><span class="mini-emoji">🔔</span><span class="mini-emoji">🔔</span></span><span>14×</span></div>
    <div class="pt-row"><span><span class="mini-emoji">🍋</span><span class="mini-emoji">🍋</span><span class="mini-emoji">🍋</span></span><span>7×</span></div>
    <div class="pt-row"><span><span class="mini-emoji">🍒</span><span class="mini-emoji">🍒</span><span class="mini-emoji">🍒</span></span><span>4×</span></div>
    <div class="pt-row"><span><span class="mini-emoji">🍒</span><span class="mini-emoji">🍒</span></span><span>возврат ставки</span></div>
  </div>

  <div class="bet">
    <BetInput bind:amount balance={balance?.balance ?? null} disabled={busy} />
  </div>

  <button class="play" disabled={busy} on:click={play}>
    {busy ? 'Барабаны крутятся…' : `Поставить ${amount}`}
  </button>

  {#if err}
    <div class="danger" style="margin-top: 10px">{err}</div>
  {/if}

  {#if last && !busy}
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

  .machine {
    background: linear-gradient(180deg, #2a2a2e, #15151a);
    border: 3px solid;
    border-color: #d4a020 #8a6510 #5b3e00 #d4a020;
    border-radius: 14px;
    padding: 14px;
    margin-bottom: 16px;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4);
  }
  .reels {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
  }
  .reel {
    position: relative;
    height: 100px; /* CELL_H */
    overflow: hidden;
    border-radius: 8px;
    background: #f7f4ee;
    box-shadow: inset 0 4px 10px rgba(0, 0, 0, 0.25);
  }
  .strip {
    position: absolute;
    inset: 0;
    will-change: transform;
  }
  .cell {
    height: 100px; /* CELL_H */
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .cell img {
    max-width: 80%;
    max-height: 80%;
    object-fit: contain;
  }
  .emoji {
    font-size: 56px;
    line-height: 1;
  }
  /* Лёгкая «тень окна» сверху/снизу — имитация стекла слот-машины */
  .window-overlay {
    position: absolute;
    left: 0;
    right: 0;
    height: 22px;
    pointer-events: none;
  }
  .window-overlay.top {
    top: 0;
    background: linear-gradient(180deg, rgba(0, 0, 0, 0.5), transparent);
  }
  .window-overlay.bottom {
    bottom: 0;
    background: linear-gradient(0deg, rgba(0, 0, 0, 0.5), transparent);
  }
  .payline {
    position: absolute;
    left: 4px;
    right: 4px;
    top: 50%;
    height: 2px;
    background: rgba(193, 39, 45, 0.65);
    transform: translateY(-50%);
    pointer-events: none;
  }

  .paytable {
    background: var(--bg-elev-2);
    border-radius: 10px;
    padding: 10px 12px;
    margin-bottom: 14px;
    font-size: 13px;
    line-height: 1.5;
  }
  .pt-title {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px;
  }
  .pt-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 2px 0;
  }
  .mini-emoji {
    font-size: 16px;
    margin-right: 2px;
  }

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
