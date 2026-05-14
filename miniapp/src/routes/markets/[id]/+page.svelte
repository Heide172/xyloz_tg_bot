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
  let presets = [50, 100, 500, 1000];
  let posting = false;

  async function load() {
    loading = true;
    err = null;
    try {
      const [m, b] = await Promise.all([api.market(marketId), api.balance()]);
      market = m;
      balance = b;
      selectedPos = m.options[0]?.position + 1 || 1;
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
  <div class="hint">Загрузка…</div>
{:else if err || !market}
  <div class="error">{err ?? 'не найдено'}</div>
{:else}
  <div class="card">
    <div class="status-line">
      <span class="badge badge-{market.status}">{market.status}</span>
      <span class="hint">{market.type}</span>
    </div>
    <h2 class="q">{market.question}</h2>
    <div class="meta">
      пул {fmtCoins(market.total_pool)} · ставок {market.bets_count}
    </div>
    <div class="meta">закрытие: {fmtDate(market.closes_at)}</div>
    {#if market.external_url}
      <div class="meta">
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
            <div class="opt-fill" style="width: {Math.max(2, o.share * 100)}%"></div>
          </div>
          <div class="opt-pool">пул {fmtCoins(o.pool)}</div>
        </button>
      {/each}
    </div>

    {#if market.status === 'open'}
      <div class="bet">
        <div class="bet-balance">
          Баланс: <strong>{balance ? fmtCoins(balance.balance) : '—'}</strong>
        </div>
        <div class="amount-row">
          <input type="number" bind:value={amount} min="10" step="10" />
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
        Победила:
        <strong>
          {market.options.find((o) => o.id === market.winning_option_id)?.label ?? '?'}
        </strong>
      </div>
    {/if}
  </div>
{/if}

<style>
  .back {
    display: inline-block;
    margin-bottom: 10px;
    font-size: 13px;
  }
  .card {
    background: var(--section-bg);
    border-radius: 14px;
    padding: 16px;
  }
  .status-line {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 8px;
  }
  .q {
    font-size: 18px;
    margin: 4px 0 12px;
    line-height: 1.35;
  }
  .meta {
    color: var(--hint);
    font-size: 13px;
    margin-bottom: 4px;
  }
  .badge {
    padding: 2px 8px;
    border-radius: 5px;
    font-size: 11px;
    text-transform: uppercase;
    background: rgba(0, 0, 0, 0.08);
  }
  .badge-open {
    background: rgba(36, 129, 204, 0.18);
    color: var(--link);
  }
  .badge-resolved {
    background: rgba(0, 128, 0, 0.18);
    color: #1e8a47;
  }
  .badge-cancelled,
  .badge-closed {
    background: rgba(128, 128, 128, 0.18);
    color: var(--hint);
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
    border: 2px solid transparent;
    border-radius: 10px;
    padding: 12px;
    text-align: left;
    cursor: pointer;
    color: var(--text);
  }
  .option.selected {
    border-color: var(--button);
  }
  .option:disabled {
    opacity: 0.6;
    cursor: default;
  }
  .opt-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 6px;
  }
  .opt-label {
    font-weight: 500;
  }
  .opt-share {
    font-variant-numeric: tabular-nums;
    color: var(--hint);
  }
  .opt-track {
    height: 6px;
    background: rgba(0, 0, 0, 0.08);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 4px;
  }
  .opt-fill {
    height: 100%;
    background: var(--button);
  }
  .opt-pool {
    font-size: 11px;
    color: var(--hint);
  }
  .bet {
    margin-top: 14px;
  }
  .bet-balance {
    font-size: 13px;
    color: var(--hint);
    margin-bottom: 8px;
  }
  .amount-row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .amount-row input {
    flex: 0 0 110px;
    padding: 10px 12px;
    border: 1px solid var(--separator);
    border-radius: 8px;
    font-size: 16px;
    background: var(--bg);
    color: var(--text);
  }
  .presets {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .preset {
    padding: 8px 10px;
    border: 0;
    background: var(--bg);
    color: var(--text);
    border-radius: 7px;
    font-size: 13px;
    cursor: pointer;
  }
  .resolved {
    margin-top: 12px;
    padding: 10px;
    background: rgba(0, 128, 0, 0.1);
    border-radius: 8px;
    font-size: 14px;
  }
  .hint {
    color: var(--hint);
  }
  .error {
    color: var(--destructive);
  }
</style>
