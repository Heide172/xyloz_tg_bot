<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins, fmtDate, shortLabel } from '$lib/format';
  import type { PortfolioBet } from '$lib/types';

  let items: PortfolioBet[] = [];
  let loading = true;
  let err: string | null = null;

  onMount(async () => {
    try {
      const data = await api.portfolio();
      items = data.items;
    } catch (e: any) {
      err = e?.message ?? 'Не удалось загрузить';
    } finally {
      loading = false;
    }
  });
</script>

<h1 class="title">Портфолио</h1>

{#if loading}
  <div class="hint">Загрузка…</div>
{:else if err}
  <div class="error">{err}</div>
{:else if items.length === 0}
  <div class="hint">У тебя нет ставок в этом чате.</div>
{:else}
  <div class="list">
    {#each items as it}
      <a class="row" href={`/markets/${it.market_id}` + window.location.search}>
        <div class="status-line">
          <span class="badge badge-{it.status}">{it.status}</span>
          <span class="date">{fmtDate(it.created_at)}</span>
        </div>
        <div class="q">{shortLabel(it.question, 100)}</div>
        <div class="bet-line">
          <span>«{it.option_label}»</span>
          <span class="amt">ставка {fmtCoins(it.amount)}</span>
        </div>
        {#if it.status === 'resolved' && it.payout !== null}
          <div class="payout {it.payout > 0 ? 'win' : 'lose'}">
            {it.payout > 0 ? '+' : ''}{fmtCoins(it.payout - it.amount)}
            ({it.payout > 0 ? 'выплата ' + fmtCoins(it.payout) : 'проигрыш'})
          </div>
        {:else if it.refunded}
          <div class="payout">возврат {fmtCoins(it.amount)}</div>
        {/if}
      </a>
    {/each}
  </div>
{/if}

<style>
  .title {
    font-size: 22px;
    margin: 4px 0 12px;
  }
  .list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .row {
    background: var(--section-bg);
    border-radius: 12px;
    padding: 14px;
    color: var(--text);
    display: block;
  }
  .status-line {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }
  .badge {
    padding: 1px 6px;
    border-radius: 4px;
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
  .date {
    font-size: 11px;
    color: var(--hint);
  }
  .q {
    font-size: 14px;
    margin-bottom: 8px;
    line-height: 1.3;
  }
  .bet-line {
    display: flex;
    justify-content: space-between;
    font-size: 13px;
    color: var(--hint);
  }
  .amt {
    font-variant-numeric: tabular-nums;
  }
  .payout {
    margin-top: 6px;
    font-size: 13px;
  }
  .payout.win {
    color: #1e8a47;
  }
  .payout.lose {
    color: var(--destructive);
  }
  .hint {
    color: var(--hint);
  }
  .error {
    color: var(--destructive);
  }
</style>
