<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';
  import type { FarmState, FarmWorker } from '$lib/types';

  let state: FarmState | null = null;
  let err: string | null = null;
  let loading = true;
  let busy = false;

  let pendingTaps = 0;
  let lastBatchAt = Date.now();
  const CLIENT_TAP_LIMIT = 20;
  let tapTimes: number[] = [];

  let bursts: { id: number; x: number; y: number; value: number }[] = [];
  let burstId = 0;

  let convertAmount = 10;
  let convertOpen = false;
  let workersOpen = true;

  let lastStateAt = Date.now();
  let nowTs = Date.now();

  // Спрайт-анимация героини: idle (покачивание) / tap (момент клика) / bonus
  let heroFrame: 'idle' | 'tap' | 'bonus' = 'idle';
  let heroTapTimer: number | null = null;
  let heroImgOk = { idle: true, tap: true, bonus: true };

  const WORKER_META: Record<string, { emoji: string; name: string }> = {
    cherry: { emoji: '🍒', name: 'Вишнёвая' },
    lemon: { emoji: '🍋', name: 'Лимонная' },
    bell: { emoji: '🔔', name: 'Колокольчик' },
    star: { emoji: '⭐', name: 'Звёздная' },
    diamond: { emoji: '💎', name: 'Бриллиантовая' }
  };
  let workerImgOk: Record<string, boolean> = {};

  $: search = typeof window !== 'undefined' ? window.location.search : '';
  $: autoAccrued = state
    ? Math.floor(((nowTs - lastStateAt) / 1000) * state.auto_rate_cps)
    : 0;
  $: displayCp = state
    ? state.cp_balance + pendingTaps * state.tap_level + autoAccrued
    : 0;
  // Теперь продаём cp на AMM-рынок (без дневного лимита).
  $: maxConvert = state ? Math.max(0, Math.floor(state.cp_balance)) : 0;

  // Реальная котировка AMM (constant-product) по живому пулу.
  let market: { rate: number; r_cp: number; r_h: number; anchor_rate: number;
                history: { ts: string; rate: number }[] } | null = null;

  function ammOut(cp: number): number {
    if (!market || cp <= 0) return 0;
    const k = market.r_cp * market.r_h;
    const out = market.r_h - k / (market.r_cp + cp);
    return Math.max(0, Math.floor(out));
  }
  $: estHryvnia = ammOut(convertAmount);
  // эффективная цена сделки и проскальзывание vs спот
  $: effRate = estHryvnia > 0 ? convertAmount / estHryvnia : 0;
  $: slipPct =
    market && estHryvnia > 0 && market.rate > 0
      ? Math.max(0, (effRate / market.rate - 1) * 100)
      : 0;
  $: devalX = market && market.anchor_rate > 0
      ? market.rate / market.anchor_rate
      : 1;

  // Лестница котировок: репрезентативные размеры от баланса.
  $: ladder = (() => {
    if (!market || maxConvert <= 0) return [];
    const cand = [1000, 10000, 100000, Math.floor(maxConvert * 0.25), maxConvert];
    const seen = new Set<number>();
    const out: { cp: number; h: number; eff: number; slip: number }[] = [];
    for (const c0 of cand) {
      const cp = Math.min(maxConvert, Math.max(1, Math.floor(c0)));
      if (cp <= 0 || seen.has(cp)) continue;
      seen.add(cp);
      const h = ammOut(cp);
      const eff = h > 0 ? cp / h : 0;
      const slip = market.rate > 0 && eff > 0
        ? Math.max(0, (eff / market.rate - 1) * 100) : 0;
      out.push({ cp, h, eff, slip });
    }
    return out.sort((a, b) => a.cp - b.cp);
  })();

  // Кривая price-impact: x = cp продано (0..maxConvert), y = ₴.
  const IW = 100, IH = 44, IP = 3;
  $: impact = (() => {
    if (!market || maxConvert <= 0) return null;
    const N = 48;
    const ys: number[] = [];
    for (let i = 0; i <= N; i++) ys.push(ammOut((i / N) * maxConvert));
    const ymax = Math.max(ys[ys.length - 1], 1);
    const X = (i: number) => IP + (i / N) * (IW - 2 * IP);
    const Y = (v: number) => IH - IP - (v / ymax) * (IH - 2 * IP);
    const pts = ys.map((v, i) => `${X(i).toFixed(2)},${Y(v).toFixed(2)}`);
    const cur = Math.min(maxConvert, Math.max(0, convertAmount || 0));
    return {
      line: 'M' + pts.join(' L'),
      area: `M${X(0).toFixed(2)},${IH} L` + pts.join(' L') +
            ` L${X(N).toFixed(2)},${IH} Z`,
      mx: IP + (cur / maxConvert) * (IW - 2 * IP),
      my: IH - IP - (ammOut(cur) / ymax) * (IH - 2 * IP)
    };
  })();

  // Биржевой график (TradingView lightweight-charts), client-only.
  let chartEl: HTMLDivElement | null = null;
  let _chart: any = null;
  let _series: any = null;
  let _ro: ResizeObserver | null = null;

  function histData(h: { ts: string; rate: number }[]) {
    const m = new Map<number, number>();
    for (const x of h) {
      const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(x.ts) ? x.ts : x.ts + 'Z';
      const t = Math.floor(Date.parse(iso) / 1000);
      if (!Number.isNaN(t)) m.set(t, x.rate); // дубль времени → последний
    }
    return [...m.entries()].sort((a, b) => a[0] - b[0])
      .map(([time, value]) => ({ time, value }));
  }

  function cssVar(name: string, fallback: string) {
    if (typeof window === 'undefined') return fallback;
    const v = getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim();
    return v || fallback;
  }

  async function initChart() {
    if (!chartEl || _chart || typeof window === 'undefined') return;
    const data = histData(market?.history ?? []);
    if (data.length < 2) return;
    const { createChart, ColorType } = await import('lightweight-charts');
    const text = cssVar('--text-muted', '#8a8f98');
    const up = data[data.length - 1].value >= data[0].value;
    const accent = up ? '#26a69a' : '#ef5350';
    _chart = createChart(chartEl, {
      width: chartEl.clientWidth,
      height: 160,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: text, fontSize: 10 },
      grid: { vertLines: { visible: false }, horzLines: { color: 'rgba(127,127,127,0.12)' } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
      crosshair: { mode: 1 },
      handleScale: true,
      handleScroll: true
    });
    _series = _chart.addAreaSeries({
      lineColor: accent,
      lineWidth: 2,
      topColor: accent + '55',
      bottomColor: accent + '05',
      priceFormat: { type: 'price', precision: 0, minMove: 1 }
    });
    _series.setData(data);
    _chart.timeScale().fitContent();
    _ro = new ResizeObserver(() => {
      if (_chart && chartEl) _chart.applyOptions({ width: chartEl.clientWidth });
    });
    _ro.observe(chartEl);
  }

  function updateChart() {
    if (!_series) { initChart(); return; }
    const data = histData(market?.history ?? []);
    if (data.length >= 2) {
      _series.setData(data);
      _chart?.timeScale().fitContent();
    }
  }

  async function loadMarket() {
    try {
      market = await api.farmMarket();
      updateChart();
    } catch {
      /* не критично — деградируем к споту из state */
    }
  }

  onDestroy(() => {
    try {
      _ro?.disconnect();
      _chart?.remove();
    } catch {
      /* ignore */
    }
    _ro = null;
    _chart = null;
    _series = null;
  });

  // Реактивно: меняется при смене heroFrame → Svelte перерисует <img>.
  $: heroSrcUrl = heroImgOk[heroFrame] ? `/farm/heroine_${heroFrame}.png` : '';

  function workerArt(w: FarmWorker): string {
    const tier = w.tier > 0 ? w.tier : 1;
    return `/farm/${w.type}_t${tier}.png`;
  }

  onMount(async () => {
    try {
      state = await api.farmState();
      lastStateAt = Date.now();
      nowTs = Date.now();
      await loadMarket();
      // DOM с chartEl уже отрисован (state выставлен) — добиваем init
      requestAnimationFrame(() => initChart());
    } catch (e: any) {
      err = e?.message ?? 'Не удалось загрузить ферму';
    } finally {
      loading = false;
    }
    // префлайт картинок героини
    (['idle', 'tap', 'bonus'] as const).forEach((f) => {
      const img = new Image();
      img.onerror = () => (heroImgOk[f] = false);
      img.src = `/farm/heroine_${f}.png`;
    });
  });

  let tickHandle: number | null = null;
  let batchHandle: number | null = null;
  let bonusHandle: number | null = null;
  onMount(() => {
    tickHandle = window.setInterval(() => (nowTs = Date.now()), 200);
    batchHandle = window.setInterval(flushTaps, 400);
    // изредка проигрываем bonus-кадр (живость), если не идёт тап
    bonusHandle = window.setInterval(() => {
      if (heroFrame === 'idle') {
        heroFrame = 'bonus';
        setTimeout(() => {
          if (heroFrame === 'bonus') heroFrame = 'idle';
        }, 900);
      }
    }, 7000);
    return () => {
      if (tickHandle !== null) clearInterval(tickHandle);
      if (batchHandle !== null) clearInterval(batchHandle);
      if (bonusHandle !== null) clearInterval(bonusHandle);
    };
  });

  function syncState(next: FarmState) {
    state = next;
    lastStateAt = Date.now();
    nowTs = Date.now();
  }

  async function flushTaps() {
    if (pendingTaps <= 0 || busy) return;
    const count = pendingTaps;
    const now = Date.now();
    const elapsedMs = Math.max(50, now - lastBatchAt);
    pendingTaps -= count;
    lastBatchAt = now;
    busy = true;
    try {
      syncState(await api.farmTap(count, elapsedMs));
    } catch (e: any) {
      err = e?.message ?? null;
      pendingTaps += count;
    } finally {
      busy = false;
    }
  }

  function tap(event: MouseEvent | TouchEvent) {
    if (!state) return;
    const now = Date.now();
    tapTimes = tapTimes.filter((t) => now - t < 1000);
    if (tapTimes.length >= CLIENT_TAP_LIMIT) return;
    tapTimes.push(now);
    pendingTaps += 1;

    // спрайт реакции
    heroFrame = 'tap';
    if (heroTapTimer !== null) clearTimeout(heroTapTimer);
    heroTapTimer = window.setTimeout(() => (heroFrame = 'idle'), 220);

    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    let x = rect.width / 2,
      y = rect.height / 2;
    if ('touches' in event && event.touches[0]) {
      x = event.touches[0].clientX - rect.left;
      y = event.touches[0].clientY - rect.top;
    } else if ('clientX' in event) {
      x = (event as MouseEvent).clientX - rect.left;
      y = (event as MouseEvent).clientY - rect.top;
    }
    const id = burstId++;
    bursts = [...bursts, { id, x, y, value: state.tap_level }];
    setTimeout(() => (bursts = bursts.filter((b) => b.id !== id)), 900);
    haptic('light');
  }

  async function upgradeTap() {
    if (!state) return;
    await flushTaps();
    try {
      syncState(await api.farmUpgradeTap());
      haptic('success');
    } catch (e: any) {
      showAlert(e?.message ?? 'Не получилось');
      haptic('error');
    }
  }

  async function hire(w: FarmWorker) {
    if (!state || busy) return;
    await flushTaps();
    try {
      syncState(await api.farmHire(w.type));
      haptic('success');
    } catch (e: any) {
      showAlert(e?.message ?? 'Не получилось');
      haptic('error');
    }
  }

  async function convert() {
    if (!state || convertAmount <= 0) return;
    await flushTaps();
    const before = state.user_balance;
    try {
      const ns = await api.farmConvert(convertAmount);
      const got = ns.user_balance - before;
      syncState(ns);
      haptic('success');
      showAlert(`Продано ${convertAmount} cp → +${got} гривен`);
      loadMarket(); // пул сдвинулся — обновляем котировку
    } catch (e: any) {
      showAlert(e?.message ?? 'Не получилось');
      haptic('error');
    }
  }

  function fmtCp(v: number): string {
    if (v >= 1_000_000) return (v / 1_000_000).toFixed(2) + 'M';
    if (v >= 1_000) return (v / 1_000).toFixed(1) + 'k';
    return Math.floor(v).toString();
  }
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Ферма</h1>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err && !state}
  <div class="danger">{err}</div>
{:else if state}
  <div class="stats card">
    <div class="stat">
      <span class="label muted">CP</span>
      <span class="value">{fmtCp(displayCp)}</span>
    </div>
    <div class="stat">
      <span class="label muted">/сек</span>
      <span class="value small">{state.auto_rate_cps.toFixed(1)}</span>
    </div>
    <div class="stat">
      <span class="label muted">Гривны</span>
      <span class="value small">{fmtCoins(state.user_balance)}</span>
    </div>
  </div>

  <button
    class="tap-zone"
    type="button"
    on:click={tap}
    on:touchstart|preventDefault={tap}
    aria-label="Тап по ферме"
  >
    <div class="hero" class:tapped={heroFrame === 'tap'} class:bonus={heroFrame === 'bonus'}>
      {#if heroSrcUrl}
        <img src={heroSrcUrl} alt="фермерша" draggable="false" />
      {:else}
        <span class="hero-fallback">🧑‍🌾</span>
      {/if}
    </div>
    {#each bursts as b (b.id)}
      <span class="burst" style="left:{b.x}px; top:{b.y}px">+{b.value}</span>
    {/each}
  </button>

  <div class="hint muted small">
    +{state.tap_level} cp за тап · пассивно {state.auto_rate_cps.toFixed(1)} cp/сек
    {#if state.auto_rate_cps > 0}
      · оффлайн до {Math.floor(state.offline_cap_seconds / 3600)}ч
    {/if}
  </div>

  <button
    class="upgrade-tap"
    on:click={upgradeTap}
    disabled={state.next_tap_cost === 0 || state.cp_balance < state.next_tap_cost}
  >
    Сила тапа → ур. {state.tap_level + 1}
    <span class="cost">{state.next_tap_cost === 0 ? 'MAX' : `${fmtCp(state.next_tap_cost)} cp`}</span>
  </button>

  <!-- Работницы -->
  <details class="section" bind:open={workersOpen}>
    <summary>Работницы фермы</summary>
    <div class="workers">
      {#each state.workers as w (w.type)}
        {@const meta = WORKER_META[w.type]}
        {@const affordable = w.next_cost > 0 && state.cp_balance >= w.next_cost}
        <div class="worker" class:hired={w.level > 0}>
          <div class="w-art">
            {#if workerImgOk[w.type] !== false}
              <img
                src={workerArt(w)}
                alt={meta.name}
                draggable="false"
                on:error={() => (workerImgOk = { ...workerImgOk, [w.type]: false })}
              />
            {:else}
              <span class="w-emoji">{meta.emoji}</span>
            {/if}
            {#if w.level > 0}
              <span class="w-tier">T{w.tier}</span>
            {/if}
          </div>
          <div class="w-info">
            <div class="w-name">
              {meta.name}
              {#if w.level > 0}<span class="muted">· ур. {w.level}</span>{/if}
            </div>
            <div class="w-rate muted small">
              {#if w.level > 0}
                {w.rate_cps.toFixed(1)} cp/сек
              {:else}
                {w.per_level_cps} cp/сек за уровень
              {/if}
            </div>
          </div>
          <button
            class="w-buy"
            class:can={affordable}
            disabled={!affordable}
            on:click={() => hire(w)}
          >
            {#if w.next_cost === 0}
              MAX
            {:else}
              {w.level === 0 ? 'Нанять' : '+1'}
              <span class="w-cost">{fmtCp(w.next_cost)}</span>
            {/if}
          </button>
        </div>
      {/each}
    </div>
  </details>

  <!-- Конвертация -->
  <details class="section" bind:open={convertOpen}>
    <summary>Продать cp на рынок</summary>
    <div class="convert">
      <div class="muted small" style="margin-bottom: 8px;">
        Это рынок (AMM): продаёшь cp в общий пул, цена падает тем сильнее,
        чем больше продаёшь за раз. Курс сам восстанавливается со временем,
        если продажи стихают — выгоднее продавать на отскоке.
      </div>
      {#if market}
        <div class="quote-box">
          <div class="qrow">
            <span class="muted small">Спот-курс</span>
            <b>{Math.round(market.rate).toLocaleString()} cp / 1₴</b>
          </div>
          <div class="qrow">
            <span class="muted small">vs базовый ({market.anchor_rate})</span>
            <b class:bad={devalX > 2}>
              {devalX >= 1 ? `cp дешевле в ${devalX.toFixed(1)}×` : `cp дороже в ${(1 / devalX).toFixed(1)}×`}
            </b>
          </div>
        </div>
        {#if market.history && market.history.length > 1}
          <div class="chart-wrap">
            <div class="muted small chart-cap">Курс cp → ₴ (история)</div>
            <div class="chart" bind:this={chartEl}></div>
          </div>
        {/if}
      {/if}
      <div class="convert-row">
        <input type="number" min="1" max={maxConvert} step="100" bind:value={convertAmount} />
        <span class="muted small">cp</span>
        <button class="preset" on:click={() => (convertAmount = Math.min(1000, maxConvert))}>1k</button>
        <button class="preset" on:click={() => (convertAmount = Math.min(10000, maxConvert))}>10k</button>
        <button class="preset" on:click={() => (convertAmount = maxConvert)}>max</button>
      </div>
      {#if impact && ladder.length}
        <div class="impact">
          <div class="muted small" style="margin: 8px 0 4px;">
            Чем больше продаёшь за раз — тем хуже курс (price impact):
          </div>
          <svg
            class="impact-svg"
            viewBox="0 0 {IW} {IH}"
            preserveAspectRatio="none"
          >
            <path d={impact.area} class="ia" />
            <path d={impact.line} class="il" />
            <line
              x1={impact.mx}
              y1="0"
              x2={impact.mx}
              y2={IH}
              class="iguide"
            />
            <circle cx={impact.mx} cy={impact.my} r="1.6" class="idot" />
          </svg>
          <div class="ladder">
            {#each ladder as r}
              <button
                class="lrow"
                class:cur={r.cp === Math.min(maxConvert, convertAmount)}
                on:click={() => (convertAmount = r.cp)}
              >
                <span>{fmtCp(r.cp)} cp</span>
                <span><b>{r.h.toLocaleString()} ₴</b></span>
                <span class="muted small"
                  >{Math.round(r.eff).toLocaleString()} cp/₴{r.slip >= 0.5
                    ? ` · −${r.slip.toFixed(0)}%`
                    : ''}</span
                >
              </button>
            {/each}
          </div>
        </div>
      {/if}
      <div class="getline" style="margin: 8px 0 10px;">
        Получишь ≈ <b>{estHryvnia.toLocaleString()} ₴</b>
        <span class="muted small">
          (за {fmtCp(convertAmount || 0)} cp · факт. {effRate ? Math.round(effRate).toLocaleString() : '—'} cp/₴{slipPct >= 0.5 ? ` · slippage −${slipPct.toFixed(1)}%` : ''})
        </span>
      </div>
      <button class="play" on:click={convert} disabled={!convertAmount || convertAmount > maxConvert || estHryvnia <= 0}>
        Продать {fmtCp(convertAmount || 0)} cp → {estHryvnia.toLocaleString()} ₴
      </button>
    </div>
  </details>

  {#if err}
    <div class="danger" style="margin-top: 10px">{err}</div>
  {/if}
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }

  .stats {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    padding: 12px 14px;
    margin-bottom: 14px;
  }
  .stat { display: flex; flex-direction: column; gap: 2px; flex: 1; }
  .stat:not(:last-child) { border-right: 1px solid var(--separator); padding-right: 10px; }
  .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .value { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }
  .value.small { font-size: 16px; }

  .tap-zone {
    position: relative;
    width: 100%;
    height: 320px;
    display: flex;
    align-items: center;
    justify-content: center;
    background:
      radial-gradient(circle at 50% 38%, #fff7e0 0%, #ffe8c4 38%, #f6cfa0 75%, #e0a878 100%);
    border: 0;
    border-radius: 16px;
    overflow: hidden;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
    margin-bottom: 8px;
    box-shadow: var(--shadow);
    padding: 0;
  }
  /* мягкое солнце-свечение за героиней */
  .tap-zone::before {
    content: '';
    position: absolute;
    width: 280px;
    height: 280px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255, 240, 200, 0.9), transparent 70%);
    filter: blur(8px);
  }
  .hero {
    position: relative;
    width: 250px;
    height: 250px;
    border-radius: 50%;
    overflow: hidden;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3), 0 0 0 4px rgba(255, 255, 255, 0.5);
    pointer-events: none;
    background: #fff;
    animation: hero-idle 2.6s ease-in-out infinite;
    transform-origin: center bottom;
  }
  .hero img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center top;
  }
  .hero-fallback { font-size: 96px; }
  /* лёгкое покачивание в простое */
  @keyframes hero-idle {
    0%, 100% { transform: translateY(0) rotate(-1.5deg); }
    50% { transform: translateY(-6px) rotate(1.5deg); }
  }
  .hero.tapped {
    animation: hero-tap 0.22s ease-out;
  }
  @keyframes hero-tap {
    0% { transform: scale(1); }
    40% { transform: scale(0.9) rotate(-3deg); }
    100% { transform: scale(1.04) rotate(0); }
  }
  .hero.bonus {
    animation: hero-bonus 0.9s ease-in-out;
  }
  @keyframes hero-bonus {
    0%, 100% { transform: scale(1) rotate(0); }
    25% { transform: scale(1.08) rotate(4deg); }
    60% { transform: scale(1.08) rotate(-4deg); }
  }

  .burst {
    position: absolute;
    pointer-events: none;
    font-size: 24px;
    font-weight: 800;
    color: #fff;
    text-shadow: 0 0 8px rgba(0, 0, 0, 0.6), 0 2px 4px rgba(0,0,0,0.5);
    transform: translate(-50%, -50%);
    animation: float-up 0.9s ease-out forwards;
  }
  @keyframes float-up {
    0% { transform: translate(-50%, -50%) scale(0.5); opacity: 0; }
    20% { transform: translate(-50%, -85%) scale(1.15); opacity: 1; }
    100% { transform: translate(-50%, -190%) scale(0.9); opacity: 0; }
  }

  .hint { margin: 6px 0 12px; text-align: center; }
  .small { font-size: 12px; }

  .upgrade-tap {
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 13px 16px;
    background: var(--accent);
    color: var(--accent-text);
    border: 0;
    border-radius: 12px;
    font-weight: 700;
    font-size: 14px;
    cursor: pointer;
    margin-bottom: 14px;
  }
  .upgrade-tap:disabled { opacity: 0.5; }
  .upgrade-tap .cost { font-variant-numeric: tabular-nums; opacity: 0.9; }

  .section {
    margin-bottom: 12px;
    background: var(--bg-elev);
    border-radius: 12px;
    padding: 12px 14px;
    box-shadow: var(--shadow);
  }
  .section summary {
    cursor: pointer;
    font-weight: 600;
    list-style: none;
    user-select: none;
  }
  .section summary::-webkit-details-marker { display: none; }
  .section summary::after {
    content: '▾';
    float: right;
    color: var(--text-muted);
    transition: transform 0.15s ease;
  }
  .section[open] summary::after { transform: rotate(180deg); }

  .workers {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 10px;
  }
  .worker {
    display: flex;
    align-items: center;
    gap: 10px;
    background: var(--bg);
    border: 1px solid var(--separator);
    border-radius: 12px;
    padding: 8px 10px;
    opacity: 0.78;
  }
  .worker.hired { opacity: 1; border-color: color-mix(in srgb, var(--accent) 40%, var(--separator)); }
  .w-art {
    position: relative;
    width: 54px;
    height: 54px;
    border-radius: 10px;
    overflow: hidden;
    flex: 0 0 auto;
    background: var(--bg-elev-2);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .w-art img { width: 100%; height: 100%; object-fit: cover; }
  .w-emoji { font-size: 30px; }
  .w-tier {
    position: absolute;
    bottom: 2px;
    right: 2px;
    background: var(--accent);
    color: var(--accent-text);
    font-size: 9px;
    font-weight: 800;
    padding: 1px 4px;
    border-radius: 4px;
  }
  .w-info { flex: 1; min-width: 0; }
  .w-name { font-weight: 600; font-size: 14px; }
  .w-rate { font-size: 12px; }
  .w-buy {
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1px;
    padding: 8px 12px;
    border: 0;
    border-radius: 9px;
    background: var(--bg-elev-2);
    color: var(--text-muted);
    font-weight: 700;
    font-size: 13px;
    cursor: pointer;
  }
  .w-buy.can { background: var(--accent); color: var(--accent-text); }
  .w-buy:disabled { cursor: default; }
  .w-cost { font-size: 11px; font-variant-numeric: tabular-nums; opacity: 0.9; }

  .convert { margin-top: 10px; }
  .quote-box {
    background: var(--bg-elev-2, rgba(127,127,127,0.08));
    border-radius: 10px; padding: 8px 10px; margin-bottom: 10px;
    display: flex; flex-direction: column; gap: 4px;
  }
  .qrow { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .qrow b { font-size: 13px; }
  .qrow b.bad { color: #ff9a9a; }
  .chart-wrap { margin-bottom: 10px; }
  .chart-cap { margin: 2px 0 4px; }
  .chart { width: 100%; height: 160px; }
  .impact { margin-bottom: 6px; }
  .impact-svg {
    width: 100%; height: 72px; display: block;
    background: rgba(127, 127, 127, 0.06); border-radius: 8px;
  }
  .impact-svg .ia { fill: var(--accent, #4aa8ff); opacity: 0.14; }
  .impact-svg .il {
    fill: none; stroke: var(--accent, #4aa8ff);
    stroke-width: 1.4; vector-effect: non-scaling-stroke;
  }
  .impact-svg .iguide {
    stroke: var(--text-muted, #8a8f98); stroke-width: 0.6;
    stroke-dasharray: 2 2; opacity: 0.6;
  }
  .impact-svg .idot { fill: var(--accent, #4aa8ff); }
  .ladder { display: flex; flex-direction: column; gap: 3px; margin-top: 6px; }
  .lrow {
    display: grid; grid-template-columns: 1fr auto 1fr; gap: 8px;
    align-items: baseline; padding: 6px 8px; border-radius: 7px;
    background: var(--bg-elev-2, rgba(127, 127, 127, 0.08));
    border: 1px solid transparent; color: var(--text); cursor: pointer;
    font-size: 13px; text-align: left;
  }
  .lrow span:last-child { text-align: right; }
  .lrow.cur { border-color: var(--accent, #4aa8ff); }
  .getline { font-size: 15px; }
  .getline b { font-size: 17px; }
  .convert-row {
    display: flex;
    gap: 6px;
    align-items: center;
    flex-wrap: wrap;
  }
  .convert-row input {
    flex: 0 0 90px;
    padding: 9px 10px;
    border: 1px solid var(--separator);
    border-radius: 8px;
    background: var(--bg);
    color: var(--text);
    font-size: 15px;
  }
  .preset {
    padding: 7px 10px;
    border: 0;
    background: var(--bg-elev-2);
    color: var(--text);
    border-radius: 7px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
  }
  .play {
    width: 100%;
    padding: 13px;
    background: var(--accent);
    color: var(--accent-text);
    border: 0;
    border-radius: 10px;
    font-weight: 700;
    font-size: 14px;
    cursor: pointer;
  }
  .play:disabled { opacity: 0.5; }
</style>
