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

<h1 class="h1">Лидерборд</h1>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="danger">{err}</div>
{:else if entries.length === 0}
  <div class="muted">Пока пусто.</div>
{:else}
  <div class="list card" style="padding: 6px">
    {#each entries as e, i}
      <div class="row" class:top={i < 3}>
        <span class="rank" class:gold={i === 0} class:silver={i === 1} class:bronze={i === 2}>
          {i + 1}
        </span>
        <span class="name">{label(e.user)}</span>
        <span class="amt">{fmtCoins(e.balance)}</span>
      </div>
    {/each}
  </div>
{/if}

<style>
  .list {
    overflow: hidden;
  }
  .row {
    display: grid;
    grid-template-columns: 40px 1fr auto;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--separator);
  }
  .row:last-child {
    border-bottom: 0;
  }
  .rank {
    width: 28px;
    height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: var(--bg-elev-2);
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    font-size: 13px;
    color: var(--text-muted);
  }
  .rank.gold {
    background: #f7d147;
    color: #5b3e00;
  }
  .rank.silver {
    background: #d3d6db;
    color: #2f3033;
  }
  .rank.bronze {
    background: #d49a64;
    color: #4a2a07;
  }
  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
  }
  .amt {
    font-variant-numeric: tabular-nums;
    font-weight: 600;
  }
</style>
