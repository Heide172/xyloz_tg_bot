<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import type { LeaderboardEntry } from '$lib/types';

  let entries: LeaderboardEntry[] = [];
  let loading = true;
  let err: string | null = null;

  onMount(async () => {
    try {
      const data = await api.leaderboard(20);
      entries = data.entries;
    } catch (e: any) {
      err = e?.message ?? 'Не удалось загрузить';
    } finally {
      loading = false;
    }
  });

  function label(u: { username: string | null; fullname: string | null }) {
    if (u.username) return `@${u.username}`;
    return u.fullname ?? 'Unknown';
  }
</script>

<h1 class="title">Лидерборд</h1>

{#if loading}
  <div class="hint">Загрузка…</div>
{:else if err}
  <div class="error">{err}</div>
{:else if entries.length === 0}
  <div class="hint">Пока пусто.</div>
{:else}
  <div class="list">
    {#each entries as e, i}
      <div class="row">
        <span class="rank">{i + 1}</span>
        <span class="name">{label(e.user)}</span>
        <span class="amt">{fmtCoins(e.balance)}</span>
      </div>
    {/each}
  </div>
{/if}

<style>
  .title {
    font-size: 22px;
    margin: 4px 0 12px;
  }
  .list {
    background: var(--section-bg);
    border-radius: 12px;
    overflow: hidden;
  }
  .row {
    display: grid;
    grid-template-columns: 32px 1fr auto;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--separator);
  }
  .row:last-child {
    border-bottom: 0;
  }
  .rank {
    color: var(--hint);
    font-variant-numeric: tabular-nums;
  }
  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .amt {
    font-variant-numeric: tabular-nums;
    font-weight: 500;
  }
  .hint {
    color: var(--hint);
  }
  .error {
    color: var(--destructive);
  }
</style>
