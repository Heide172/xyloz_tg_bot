<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins, fmtDate, shortLabel } from '$lib/format';
  import type { Market } from '$lib/types';

  let items: Market[] = [];
  let loading = true;
  let err: string | null = null;
  let status: 'open' | 'closed' | 'resolved' | 'all' = 'open';

  async function load() {
    loading = true;
    err = null;
    try {
      const data = await api.marketsList(status);
      items = data.items;
    } catch (e: any) {
      err = e?.message ?? 'Не удалось загрузить';
    } finally {
      loading = false;
    }
  }

  onMount(load);
</script>

<h1 class="h1">Рынки</h1>

<div class="actions">
  <a class="action" href={`/markets/create${typeof window !== 'undefined' ? window.location.search : ''}`}>
    + Создать рынок
  </a>
  <a class="action" href={`/markets/import${typeof window !== 'undefined' ? window.location.search : ''}`}>
    Импорт
  </a>
</div>

<div class="tabs">
  {#each ['open', 'closed', 'resolved', 'all'] as tab}
    <button
      class="tab"
      class:active={status === tab}
      on:click={() => {
        status = tab;
        load();
      }}
    >
      {tab}
    </button>
  {/each}
</div>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="danger">{err}</div>
{:else if items.length === 0}
  <div class="muted">Рынков нет.</div>
{:else}
  <div class="list">
    {#each items as m}
      <a class="row card" href={`/markets/${m.id}` + window.location.search}>
        <div class="head-line">
          <span class="badge badge-{m.status}">{m.status}</span>
          <span class="muted small">пул {fmtCoins(m.total_pool)} · ставок {m.bets_count}</span>
        </div>
        <div class="q">{shortLabel(m.question, 110)}</div>
        <div class="bars">
          {#each m.options as o}
            <div class="bar">
              <div class="bar-label" title={o.label}>{shortLabel(o.label, 24)}</div>
              <div class="bar-track">
                <div class="bar-fill" style="width: {Math.max(3, o.share * 100)}%"></div>
              </div>
              <div class="bar-val muted">{(o.share * 100).toFixed(0)}%</div>
            </div>
          {/each}
        </div>
        <div class="muted small">закрытие: {fmtDate(m.closes_at)}</div>
      </a>
    {/each}
  </div>
{/if}

<style>
  .actions {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
  }
  .action {
    flex: 1;
    text-align: center;
    padding: 11px;
    background: var(--bg-elev);
    color: var(--text);
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    box-shadow: var(--shadow);
  }
  .tabs {
    display: flex;
    gap: 6px;
    margin-bottom: 14px;
    background: var(--bg-elev);
    padding: 4px;
    border-radius: 11px;
  }
  .tab {
    flex: 1;
    padding: 8px 10px;
    border: 0;
    background: transparent;
    color: var(--text-muted);
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    text-transform: capitalize;
    transition: all 0.15s ease;
  }
  .tab.active {
    background: var(--bg);
    color: var(--text);
    box-shadow: var(--shadow);
  }
  .list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .row {
    display: block;
    color: var(--text);
    transition: transform 0.15s ease;
  }
  .row:active {
    transform: scale(0.99);
  }
  .head-line {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
  }
  .small {
    font-size: 12px;
  }
  .q {
    font-weight: 500;
    margin-bottom: 12px;
    line-height: 1.4;
  }
  .bars {
    display: flex;
    flex-direction: column;
    gap: 7px;
    margin-bottom: 10px;
  }
  .bar {
    display: grid;
    grid-template-columns: 90px 1fr 40px;
    align-items: center;
    gap: 8px;
    font-size: 13px;
  }
  .bar-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .bar-track {
    height: 8px;
    background: var(--bg-elev-2);
    border-radius: 4px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 4px;
  }
  .bar-val {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
</style>
