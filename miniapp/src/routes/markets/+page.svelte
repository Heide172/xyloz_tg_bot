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

<h1 class="title">Рынки</h1>

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
  <div class="hint">Загрузка…</div>
{:else if err}
  <div class="error">{err}</div>
{:else if items.length === 0}
  <div class="hint">Рынков нет.</div>
{:else}
  <div class="list">
    {#each items as m}
      <a class="row" href={`/markets/${m.id}` + window.location.search}>
        <div class="row-q">{shortLabel(m.question, 90)}</div>
        <div class="row-meta">
          <span class="badge badge-{m.status}">{m.status}</span>
          <span>пул {fmtCoins(m.total_pool)}</span>
          <span>ставок {m.bets_count}</span>
        </div>
        <div class="bars">
          {#each m.options as o}
            <div class="bar">
              <div class="bar-label">{shortLabel(o.label, 28)}</div>
              <div class="bar-track">
                <div class="bar-fill" style="width: {Math.max(2, o.share * 100)}%"></div>
              </div>
              <div class="bar-val">{(o.share * 100).toFixed(0)}%</div>
            </div>
          {/each}
        </div>
        <div class="row-foot">закрытие: {fmtDate(m.closes_at)}</div>
      </a>
    {/each}
  </div>
{/if}

<style>
  .title {
    font-size: 22px;
    margin: 4px 0 12px;
  }
  .tabs {
    display: flex;
    gap: 6px;
    margin-bottom: 12px;
  }
  .tab {
    flex: 1;
    padding: 8px 10px;
    border: 0;
    background: var(--section-bg);
    color: var(--text);
    border-radius: 8px;
    font-size: 13px;
    cursor: pointer;
  }
  .tab.active {
    background: var(--button);
    color: var(--button-text);
  }
  .list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .row {
    display: block;
    background: var(--section-bg);
    border-radius: 12px;
    padding: 14px;
    color: var(--text);
  }
  .row-q {
    font-weight: 500;
    margin-bottom: 8px;
    line-height: 1.35;
  }
  .row-meta {
    display: flex;
    gap: 10px;
    font-size: 12px;
    color: var(--hint);
    margin-bottom: 10px;
    flex-wrap: wrap;
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
  .bars {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: 8px;
  }
  .bar {
    display: grid;
    grid-template-columns: 90px 1fr 40px;
    align-items: center;
    gap: 8px;
    font-size: 13px;
  }
  .bar-label {
    color: var(--hint);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .bar-track {
    height: 8px;
    background: rgba(0, 0, 0, 0.08);
    border-radius: 4px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%;
    background: var(--button);
    border-radius: 4px;
  }
  .bar-val {
    text-align: right;
    color: var(--hint);
    font-variant-numeric: tabular-nums;
  }
  .row-foot {
    font-size: 12px;
    color: var(--hint);
  }
  .hint {
    color: var(--hint);
  }
  .error {
    color: var(--destructive);
  }
</style>
