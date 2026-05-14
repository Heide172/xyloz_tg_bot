<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import { fmtCoins, fmtDate, shortLabel } from '$lib/format';
  import { getTg, haptic, showAlert } from '$lib/tg';
  import type { BalanceResponse, Market } from '$lib/types';

  $: marketId = Number($page.params.id);
  let market: Market | null = null;
  let balance: BalanceResponse | null = null;
  let loading = true;
  let err: string | null = null;

  let selectedPos = 1;
  let amount = 100;
  const presets = [50, 100, 500, 1000];
  let posting = false;

  async function load() {
    loading = true;
    err = null;
    try {
      const [m, b] = await Promise.all([api.market(marketId), api.balance()]);
      market = m;
      balance = b;
      const first = m.options[0];
      selectedPos = first ? first.position + 1 : 1;
    } catch (e: any) {
      err = e?.message ?? 'Не удалось загрузить';
    } finally {
      loading = false;
    }
  }

  async function placeBet() {
    if (!market || posting) return;
    if (amount < 10) {
      showAlert('Минимум 10 коинов');
      return;
    }
    posting = true;
    haptic('light');
    try {
      const result = await api.placeBet(marketId, { option_position: selectedPos, amount });
      haptic('success');
      showAlert(`Ставка ${result.option_label} принята. Баланс: ${result.user_balance_after}`);
      await load();
    } catch (e: any) {
      haptic('error');
      showAlert(e?.message ?? 'Не получилось');
    } finally {
      posting = false;
    }
  }

  let mainBtnHandler: (() => void) | null = null;
  onMount(async () => {
    await load();
    const tg = getTg();
    if (tg?.MainButton) {
      mainBtnHandler = () => placeBet();
      tg.MainButton.onClick(mainBtnHandler);
      updateMainButton();
    }
  });

  onDestroy(() => {
    const tg = getTg();
    if (tg?.MainButton) {
      if (mainBtnHandler) tg.MainButton.offClick(mainBtnHandler);
      tg.MainButton.hide();
    }
  });

  function updateMainButton() {
    const tg = getTg();
    if (!tg?.MainButton || !market) return;
    if (market.status !== 'open') {
      tg.MainButton.hide();
      return;
    }
    const opt = market.options.find((o) => o.position + 1 === selectedPos);
    tg.MainButton.setText(`Поставить ${amount} на «${shortLabel(opt?.label ?? '?', 20)}»`);
    tg.MainButton.show();
    if (posting) tg.MainButton.showProgress();
    else tg.MainButton.hideProgress();
  }

  $: {
    selectedPos;
    amount;
    posting;
    market;
    updateMainButton();
  }
</script>

<a class="back" href={`/markets` + window.location.search}>← к рынкам</a>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err || !market}
  <div class="danger">{err ?? 'не найдено'}</div>
{:else}
  <section class="card">
    <div class="head">
      <span class="badge badge-{market.status}">{market.status}</span>
      <span class="muted small">{market.type}</span>
    </div>
    <h2 class="q">{market.question}</h2>
    <div class="meta">
      <span><strong>{fmtCoins(market.total_pool)}</strong> в пуле</span>
      <span class="muted">·</span>
      <span><strong>{market.bets_count}</strong> ставок</span>
    </div>
    <div class="muted small" style="margin-top: 4px">закрытие: {fmtDate(market.closes_at)}</div>
    {#if market.external_url}
      <div class="small" style="margin-top: 4px">
        <a href={market.external_url} target="_blank" rel="noreferrer">внешний рынок ↗</a>
      </div>
    {/if}

    <div class="options">
      {#each market.options as o}
        <button
          class="option"
          class:selected={selectedPos === o.position + 1}
          on:click={() => (selectedPos = o.position + 1)}
          disabled={market.status !== 'open'}
        >
          <div class="opt-row">
            <span class="opt-label">{o.label}</span>
            <span class="opt-share">{(o.share * 100).toFixed(0)}%</span>
          </div>
          <div class="opt-track">
            <div class="opt-fill" style="width: {Math.max(3, o.share * 100)}%"></div>
          </div>
          <div class="opt-pool muted">пул {fmtCoins(o.pool)}</div>
        </button>
      {/each}
    </div>

    {#if market.status === 'open'}
      <div class="bet">
        <div class="bet-balance muted small">
          Баланс: <strong style="color: var(--text);">{balance ? fmtCoins(balance.balance) : '—'}</strong>
        </div>
        <div class="amount-row">
          <input
            type="number"
            bind:value={amount}
            min="10"
            step="10"
            inputmode="numeric"
          />
          <div class="presets">
            {#each presets as p}
              <button class="preset" on:click={() => (amount = p)}>{p}</button>
            {/each}
            <button class="preset" on:click={() => (amount = balance?.balance ?? amount)}>all</button>
          </div>
        </div>
      </div>
    {:else if market.winning_option_id !== null}
      <div class="resolved">
        Победила: <strong>{market.options.find((o) => o.id === market.winning_option_id)?.label ?? '?'}</strong>
      </div>
    {/if}
  </section>
{/if}

<style>
  .back {
    display: inline-block;
    margin-bottom: 12px;
    font-size: 14px;
    color: var(--text-muted);
  }
  .head {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 10px;
  }
  .small {
    font-size: 12px;
  }
  .q {
    font-size: 19px;
    margin: 4px 0 14px;
    line-height: 1.35;
    font-weight: 600;
  }
  .meta {
    display: flex;
    gap: 8px;
    align-items: baseline;
    font-size: 14px;
  }
  .options {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin: 18px 0 12px;
  }
  .option {
    width: 100%;
    background: var(--bg);
    border: 2px solid var(--separator);
    border-radius: 12px;
    padding: 14px;
    text-align: left;
    cursor: pointer;
    color: var(--text);
    transition: all 0.15s ease;
  }
  .option:hover {
    border-color: color-mix(in srgb, var(--accent) 50%, var(--separator));
  }
  .option.selected {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .option:disabled {
    opacity: 0.6;
    cursor: default;
  }
  .opt-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 8px;
  }
  .opt-label {
    font-weight: 600;
    font-size: 15px;
  }
  .opt-share {
    font-variant-numeric: tabular-nums;
    color: var(--text-muted);
    font-size: 13px;
  }
  .opt-track {
    height: 6px;
    background: var(--bg-elev-2);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 6px;
  }
  .opt-fill {
    height: 100%;
    background: var(--accent);
  }
  .opt-pool {
    font-size: 12px;
  }
  .bet {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--separator);
  }
  .bet-balance {
    margin-bottom: 10px;
  }
  .amount-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .amount-row input {
    flex: 0 0 110px;
    padding: 11px 12px;
    border: 1px solid var(--separator);
    border-radius: 9px;
    font-size: 16px;
    background: var(--bg);
  }
  .presets {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    flex: 1;
  }
  .preset {
    padding: 8px 12px;
    border: 0;
    background: var(--bg-elev-2);
    color: var(--text);
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
  }
  .resolved {
    margin-top: 14px;
    padding: 12px;
    background: var(--positive-soft);
    color: var(--positive);
    border-radius: 10px;
    font-size: 14px;
  }
</style>
