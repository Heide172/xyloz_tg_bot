<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins, fmtDate, shortLabel } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';
  import type { Market } from '$lib/types';

  let items: Market[] = [];
  let loading = true;
  let err: string | null = null;
  let busyId: number | null = null;

  async function load() {
    loading = true;
    try {
      const data = await api.marketsList('all');
      items = data.items.filter((m) => m.status === 'open' || m.status === 'closed');
    } catch (e: any) {
      err = e?.message;
    } finally {
      loading = false;
    }
  }

  onMount(load);

  async function resolveAs(m: Market, pos: number) {
    if (busyId !== null) return;
    if (!confirm(`Закрыть «${shortLabel(m.question, 50)}» с победителем «${m.options[pos - 1]?.label}»?`)) return;
    busyId = m.id;
    try {
      await api.adminMarketResolve(m.id, pos);
      haptic('success');
      await load();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busyId = null;
    }
  }

  async function cancel(m: Market) {
    if (busyId !== null) return;
    if (!confirm(`Отменить «${shortLabel(m.question, 50)}» с возвратом всех ставок?`)) return;
    busyId = m.id;
    try {
      await api.adminMarketCancel(m.id);
      haptic('success');
      await load();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busyId = null;
    }
  }

  $: search = typeof window !== 'undefined' ? window.location.search : '';
</script>

<a class="back" href={`/admin${search}`}>← к админке</a>
<h1 class="h1">Управление рынками</h1>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="danger">{err}</div>
{:else if items.length === 0}
  <div class="muted">Нет рынков для управления (open / closed).</div>
{:else}
  <div class="list">
    {#each items as m}
      <section class="card">
        <div class="head">
          <span class="badge badge-{m.status}">{m.status}</span>
          <span class="muted small">#{m.id} · пул {fmtCoins(m.total_pool)} · {m.bets_count} ставок</span>
        </div>
        <div class="q">{shortLabel(m.question, 110)}</div>
        <div class="muted small">закрытие: {fmtDate(m.closes_at)}</div>

        <div class="opts">
          <div class="muted small" style="margin-bottom: 6px;">Резолвить как победителя:</div>
          {#each m.options as o, i}
            <button
              class="opt-btn"
              disabled={busyId === m.id}
              on:click={() => resolveAs(m, o.position + 1)}
            >
              {i + 1}. {shortLabel(o.label, 30)} <span class="muted">· {(o.share * 100).toFixed(0)}%</span>
            </button>
          {/each}
          <button
            class="cancel-btn"
            disabled={busyId === m.id}
            on:click={() => cancel(m)}
          >
            Отменить (возврат ставок)
          </button>
        </div>
      </section>
    {/each}
  </div>
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .list { display: flex; flex-direction: column; gap: 12px; }
  .head {
    display: flex; justify-content: space-between; align-items: center; gap: 10px;
    margin-bottom: 8px;
  }
  .small { font-size: 12px; }
  .q { font-weight: 500; margin-bottom: 8px; line-height: 1.4; }
  .opts { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--separator); }
  .opt-btn {
    display: block; width: 100%; text-align: left;
    padding: 9px 11px; margin-bottom: 5px;
    border: 1px solid var(--separator); background: var(--bg);
    color: var(--text); border-radius: 8px; cursor: pointer;
    font-size: 13px;
  }
  .opt-btn:hover { border-color: var(--accent); }
  .opt-btn:disabled { opacity: 0.5; }
  .cancel-btn {
    display: block; width: 100%;
    margin-top: 8px; padding: 9px 11px;
    border: 1px solid rgba(204, 41, 41, 0.4); background: transparent;
    color: var(--destructive); border-radius: 8px; cursor: pointer;
    font-size: 13px; font-weight: 500;
  }
  .cancel-btn:disabled { opacity: 0.5; }
</style>
