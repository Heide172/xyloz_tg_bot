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

<h1 class="h1">Портфолио</h1>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="danger">{err}</div>
{:else if items.length === 0}
  <div class="muted">У тебя нет ставок в этом чате.</div>
{:else}
  <div class="list">
    {#each items as it}
      <a class="row card" href={`/markets/${it.market_id}` + window.location.search}>
        <div class="head">
          <span class="badge badge-{it.status}">{it.status}</span>
          <span class="muted small">{fmtDate(it.created_at)}</span>
        </div>
        <div class="q">{shortLabel(it.question, 110)}</div>
        <div class="bet-line">
          <span>на «<strong>{it.option_label}</strong>»</span>
          <span class="muted">{fmtCoins(it.amount)}</span>
        </div>
        {#if it.status === 'resolved' && it.payout !== null && it.payout !== undefined}
          {#if it.payout > 0}
            <div class="payout success">
              <strong>+{fmtCoins(it.payout - it.amount)}</strong>
              <span class="muted small">(выплата {fmtCoins(it.payout)})</span>
            </div>
          {:else}
            <div class="payout danger">проигрыш −{fmtCoins(it.amount)}</div>
          {/if}
        {:else if it.refunded}
          <div class="payout muted">возврат {fmtCoins(it.amount)}</div>
        {/if}
      </a>
    {/each}
  </div>
{/if}

<style>
  .list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .row {
    display: block;
    color: var(--text);
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  .small {
    font-size: 12px;
  }
  .q {
    font-size: 14px;
    margin-bottom: 10px;
    line-height: 1.35;
  }
  .bet-line {
    display: flex;
    justify-content: space-between;
    font-size: 14px;
  }
  .payout {
    margin-top: 8px;
    font-size: 14px;
    padding-top: 8px;
    border-top: 1px solid var(--separator);
  }
</style>
