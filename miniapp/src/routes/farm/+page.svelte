<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';
  import type { FarmState } from '$lib/types';

  let state: FarmState | null = null;
  let err: string | null = null;
  let loading = true;
  let busy = false;

  // Локальный буфер тапов: посылаем батчами раз в 400мс
  let pendingTaps = 0;
  let lastBatchAt = Date.now();

  // Клиентский rate-limit, синхронный с серверным (server MAX_CPS=30).
  // Держим 20/сек — гарантия что сервер примет ВСЕ тапы и баланс не
  // отскочит назад из-за серверного среза anti-cheat.
  const CLIENT_TAP_LIMIT = 20;
  let tapTimes: number[] = [];

  // Поплавки "+N" над тапом
  let bursts: { id: number; x: number; y: number; value: number }[] = [];
  let burstId = 0;

  // Конвертация
  let convertAmount = 10;

  // Анимация: для пульса cherry-girl
  let tapPulse = 0;

  let convertOpen = false;
  let upgradesOpen = false;

  // Детерминированный расчёт отображаемого CP:
  //   displayCp = серверный cp_balance
  //             + неотправленные тапы (pendingTaps × tap_level)
  //             + авто-доход с момента последнего синка
  // Монотонно растёт между синками; при синке сервер уже учёл и тапы,
  // и авто за elapsed, поэтому скачков назад нет.
  let lastStateAt = Date.now();
  let nowTs = Date.now(); // обновляется тикером для реактивности

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
        Math.min(
          state.daily_remaining,
          Math.floor(state.cp_balance / state.cp_per_hryvnia),
          state.bank_balance
        )
      )
    : 0;

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
  });

  let tickHandle: number | null = null;
  let batchHandle: number | null = null;
  onMount(() => {
    tickHandle = window.setInterval(() => {
      nowTs = Date.now();
    }, 200);
    batchHandle = window.setInterval(flushTaps, 400);
    return () => {
      if (tickHandle !== null) clearInterval(tickHandle);
      if (batchHandle !== null) clearInterval(batchHandle);
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
    // Захватываем count, но pendingTaps НЕ обнуляем в 0 — вычитаем
    // отправленное. Новые тапы во время запроса останутся в очереди.
    pendingTaps -= count;
    lastBatchAt = now;
    busy = true;
    try {
      const next = await api.farmTap(count, elapsedMs);
      syncState(next);
    } catch (e: any) {
      err = e?.message ?? null;
      // не подтвердилось — вернём тапы в очередь
      pendingTaps += count;
    } finally {
      busy = false;
    }
  }

  function tap(event: MouseEvent | TouchEvent) {
    if (!state) return;

    // Rolling-window throttle: не больше CLIENT_TAP_LIMIT тапов/сек.
    // Сверхбыстрые тапы тихо игнорируем (без burst), чтобы сервер
    // засчитал ровно столько же и баланс не откатывался.
    const now = Date.now();
    tapTimes = tapTimes.filter((t) => now - t < 1000);
    if (tapTimes.length >= CLIENT_TAP_LIMIT) return;
    tapTimes.push(now);

    pendingTaps += 1;

    // Burst анимация на месте клика
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    let x = 0, y = 0;
    if ('touches' in event && event.touches[0]) {
      x = event.touches[0].clientX - rect.left;
      y = event.touches[0].clientY - rect.top;
    } else if ('clientX' in event) {
      x = event.clientX - rect.left;
      y = event.clientY - rect.top;
    } else {
      x = rect.width / 2;
      y = rect.height / 2;
    }
    const id = burstId++;
    bursts = [...bursts, { id, x, y, value: state.tap_level }];
    setTimeout(() => {
      bursts = bursts.filter((b) => b.id !== id);
    }, 900);

    tapPulse += 1;
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

  async function upgradeAuto() {
    if (!state) return;
    await flushTaps();
    try {
      syncState(await api.farmUpgradeAuto());
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
      <span class="label muted">Гривен</span>
      <span class="value small">{fmtCoins(state.user_balance)}</span>
    </div>
  </div>

  <!-- Тап-зона -->
  <button class="tap-zone" type="button" on:click={tap} on:touchstart|preventDefault={tap} aria-label="Тап по ферме">
    <div class="tap-target">
      <img src="/slots/cherry.png" alt="ферма" draggable="false" />
    </div>
    {#each bursts as b (b.id)}
      <span class="burst" style="left: {b.x}px; top: {b.y}px;">+{b.value}</span>
    {/each}
  </button>

  <div class="hint muted small">
    +{state.tap_level} cp за тап · автокликер {state.auto_rate_cps.toFixed(1)} cp/сек
    {#if state.auto_level > 0}
      · оффлайн до {Math.floor(state.offline_cap_seconds / 3600)}ч
    {/if}
  </div>

  <!-- Апгрейды -->
  <details class="section" bind:open={upgradesOpen}>
    <summary>Апгрейды</summary>
    <div class="upgrades">
      <button
        class="upgrade"
        on:click={upgradeTap}
        disabled={state.next_tap_cost === 0 || state.cp_balance < state.next_tap_cost}
      >
        <div class="up-row">
          <span class="up-title">Сила тапа</span>
          <span class="up-level muted">level {state.tap_level}</span>
        </div>
        <div class="up-row small">
          <span class="muted">+1 cp за тап</span>
          <span>
            {state.next_tap_cost === 0 ? 'MAX' : `${fmtCp(state.next_tap_cost)} cp`}
          </span>
        </div>
      </button>

      <button
        class="upgrade"
        on:click={upgradeAuto}
        disabled={state.next_auto_cost === 0 || state.cp_balance < state.next_auto_cost}
      >
        <div class="up-row">
          <span class="up-title">Автокликер</span>
          <span class="up-level muted">level {state.auto_level}</span>
        </div>
        <div class="up-row small">
          <span class="muted">+0.5 cp/сек</span>
          <span>
            {state.next_auto_cost === 0 ? 'MAX' : `${fmtCp(state.next_auto_cost)} cp`}
          </span>
        </div>
      </button>
    </div>
  </details>

  <!-- Конвертация -->
  <details class="section" bind:open={convertOpen}>
    <summary>Конвертация в гривны</summary>
    <div class="convert">
      <div class="muted small" style="margin-bottom: 8px;">
        Курс: {state.cp_per_hryvnia} cp → 1 гривна.
        Лимит: {state.daily_remaining}/{state.daily_cap} в сутки.
        Банк чата: {fmtCoins(state.bank_balance)} (это потолок).
      </div>
      <div class="convert-row">
        <input
          type="number"
          min="1"
          max={maxConvert}
          step="10"
          bind:value={convertAmount}
        />
        <span class="muted small">гривен</span>
        <button class="preset" on:click={() => (convertAmount = Math.min(10, maxConvert))}>10</button>
        <button class="preset" on:click={() => (convertAmount = Math.min(100, maxConvert))}>100</button>
        <button class="preset" on:click={() => (convertAmount = maxConvert)}>max</button>
      </div>
      <div class="muted small" style="margin: 6px 0 10px;">
        Стоимость: {fmtCp((convertAmount || 0) * state.cp_per_hryvnia)} cp ·
        Доступно: max {maxConvert}
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
    align-items: stretch;
    gap: 10px;
    padding: 12px 14px;
    margin-bottom: 14px;
  }
  .stat {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
  }
  .stat:not(:last-child) { border-right: 1px solid var(--separator); padding-right: 10px; }
  .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .value { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }
  .value.small { font-size: 16px; }

  .tap-zone {
    position: relative;
    width: 100%;
    height: 280px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: radial-gradient(circle at 50% 60%, var(--bg-elev), var(--bg));
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
  .tap-target {
    width: 200px;
    height: 200px;
    border-radius: 50%;
    overflow: hidden;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
    will-change: transform;
    transition: transform 0.07s ease-out;
    pointer-events: none;
  }
  .tap-zone:active .tap-target {
    transform: scale(0.92);
  }
  .tap-target img {
    width: 100%; height: 100%; object-fit: cover;
    pointer-events: none;
  }
  .burst {
    position: absolute;
    pointer-events: none;
    font-size: 22px;
    font-weight: 800;
    color: var(--positive);
    text-shadow: 0 0 6px rgba(0, 0, 0, 0.4);
    transform: translate(-50%, -50%);
    animation: float-up 0.9s ease-out forwards;
  }
  @keyframes float-up {
    from {
      transform: translate(-50%, -50%) scale(0.5);
      opacity: 0;
    }
    20% {
      transform: translate(-50%, -80%) scale(1.1);
      opacity: 1;
    }
    to {
      transform: translate(-50%, -180%) scale(0.9);
      opacity: 0;
    }
  }

  .hint { margin-top: 6px; margin-bottom: 14px; text-align: center; }
  .small { font-size: 12px; }

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

  .upgrades {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 10px;
  }
  .upgrade {
    background: var(--bg);
    border: 1px solid var(--separator);
    border-radius: 10px;
    padding: 10px 12px;
    text-align: left;
    cursor: pointer;
    color: var(--text);
  }
  .upgrade:disabled { opacity: 0.5; cursor: default; }
  .up-row { display: flex; justify-content: space-between; align-items: baseline; }
  .up-row + .up-row { margin-top: 4px; }
  .up-title { font-weight: 600; }
  .up-level { font-size: 12px; }

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
    width: 100%; padding: 13px;
    background: var(--accent); color: var(--accent-text);
    border: 0; border-radius: 10px; font-weight: 700; font-size: 14px; cursor: pointer;
  }
  .play:disabled { opacity: 0.5; }
</style>
