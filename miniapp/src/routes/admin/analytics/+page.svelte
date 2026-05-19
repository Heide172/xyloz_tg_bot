<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';

  let hours = 24;
  let usage: Awaited<ReturnType<typeof api.adminAnalytics>> | null = null;
  let perf: Awaited<ReturnType<typeof api.adminMetrics>> | null = null;
  let err: string | null = null;
  let loading = true;

  async function load() {
    loading = true;
    err = null;
    try {
      [usage, perf] = await Promise.all([
        api.adminAnalytics(hours),
        api.adminMetrics().catch(() => null as any)
      ]);
    } catch (e: any) {
      err = e?.message ?? 'Ошибка';
    } finally {
      loading = false;
    }
  }
  onMount(load);

  $: search = typeof window !== 'undefined' ? window.location.search : '';
</script>

<a class="back" href={`/admin${search}`}>← назад</a>
<h1 class="h1">Аналитика</h1>

<div class="tabs">
  {#each [6, 24, 72, 168] as h}
    <button class="tab" class:active={hours === h} on:click={() => { hours = h; load(); }}>
      {h}ч
    </button>
  {/each}
</div>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="card danger">{err}</div>
{:else}
  <section class="card">
    <h2 class="h2">Usage за {usage?.hours}ч</h2>
    <div class="big">{usage?.total ?? 0} <span class="muted small">событий · {usage?.unique_users ?? 0} юзеров</span></div>
    <div class="cols">
      <div>
        <div class="muted small lbl">Экраны</div>
        {#each usage?.views ?? [] as v}
          <div class="row"><span>{v.name}</span><b>{v.n}</b></div>
        {:else}
          <div class="muted small">—</div>
        {/each}
      </div>
      <div>
        <div class="muted small lbl">Действия</div>
        {#each usage?.actions ?? [] as a}
          <div class="row"><span>{a.name}</span><b>{a.n}</b></div>
        {:else}
          <div class="muted small">—</div>
        {/each}
      </div>
    </div>
  </section>

  <section class="card">
    <h2 class="h2">Перф API</h2>
    {#if !perf?.enabled}
      <div class="muted small">Метрики недоступны (нет Redis или пусто).</div>
    {:else}
      {#if perf.pool && Object.keys(perf.pool).length}
        <div class="muted small lbl">db-pool (co/size+ovf): {Object.entries(perf.pool).map(([k, v]) => `${k}:${v}`).join('  ')}</div>
      {/if}
      {#each perf.routes as r}
        <div class="row">
          <span>{r.method} {r.route}</span>
          <b>n={r.n} avg={r.avg_ms} p95{r.p95}{r.err5 ? ` · ${r.err5}×5xx` : ''}</b>
        </div>
      {:else}
        <div class="muted small">запросов ещё не было</div>
      {/each}
    {/if}
  </section>
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .h2 { font-size: 15px; margin: 0 0 8px; }
  .small { font-size: 12px; }
  .big { font-size: 22px; font-weight: 700; margin-bottom: 12px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
  .tab {
    padding: 7px 14px; border: 1px solid var(--separator); background: var(--bg);
    color: var(--text); border-radius: 999px; font-size: 13px; cursor: pointer;
  }
  .tab.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
  .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .lbl { margin-bottom: 4px; }
  .row {
    display: flex; justify-content: space-between; gap: 8px;
    font-size: 13px; padding: 3px 0; border-bottom: 1px solid var(--separator);
  }
  .row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .danger { color: #ff9a9a; }
</style>
