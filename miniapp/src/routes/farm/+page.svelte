<script lang="ts">
  import { onMount } from 'svelte';
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
  $: maxConvert = state
    ? Math.max(
        0,
        Math.min(state.daily_remaining, Math.floor(state.cp_balance / state.cp_per_hryvnia))
      )
    : 0;

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
    try {
      syncState(await api.farmConvert(convertAmount));
      haptic('success');
      showAlert(`+${convertAmount} гривен на баланс`);
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
    <summary>Конвертация в гривны</summary>
    <div class="convert">
      <div class="muted small" style="margin-bottom: 8px;">
        Курс: {state.cp_per_hryvnia} cp → 1 гривна (растёт с эмиссией чата).
        Лимит: {state.daily_remaining}/{state.daily_cap} в сутки.
      </div>
      <div class="convert-row">
        <input type="number" min="1" max={maxConvert} step="10" bind:value={convertAmount} />
        <span class="muted small">гривен</span>
        <button class="preset" on:click={() => (convertAmount = Math.min(10, maxConvert))}>10</button>
        <button class="preset" on:click={() => (convertAmount = Math.min(100, maxConvert))}>100</button>
        <button class="preset" on:click={() => (convertAmount = maxConvert)}>max</button>
      </div>
      <div class="muted small" style="margin: 6px 0 10px;">
        Стоимость: {fmtCp((convertAmount || 0) * state.cp_per_hryvnia)} cp · max {maxConvert}
      </div>
      <button class="play" on:click={convert} disabled={!convertAmount || convertAmount > maxConvert}>
        Конвертировать {convertAmount} гривен
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
