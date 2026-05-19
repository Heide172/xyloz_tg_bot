<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { haptic, showAlert } from '$lib/tg';

  type Item = {
    id: number;
    kind: 'bug' | 'idea';
    status: string;
    text: string;
    chat_id: number | null;
    created_at: string | null;
    default_reward: number;
  };

  let items: Item[] = [];
  let amounts: Record<number, number> = {};
  let loading = true;
  let err: string | null = null;
  let busy: number | null = null;

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  async function load() {
    loading = true;
    err = null;
    try {
      const r = await api.adminFeedbackList();
      items = r.items;
      amounts = {};
      for (const it of items) amounts[it.id] = it.default_reward;
    } catch (e: any) {
      err = e?.message ?? 'Ошибка загрузки';
    } finally {
      loading = false;
    }
  }

  onMount(load);

  async function close(it: Item, amount: number) {
    if (busy != null) return;
    busy = it.id;
    try {
      const res = await api.adminFeedbackClose(it.id, amount);
      items = items.filter((x) => x.id !== it.id);
      haptic('success');
      if (res.credited) {
        showAlert(`#${res.id} закрыта. ${res.author_name ?? 'автор'} +${res.reward}г`);
      } else {
        showAlert(`#${res.id} закрыта без выплаты`);
      }
    } catch (e: any) {
      haptic('error');
      showAlert(e?.message ?? 'Не удалось закрыть');
    } finally {
      busy = null;
    }
  }
</script>

<a class="back" href={`/admin${search}`}>← назад</a>
<h1 class="h1">Обратная связь</h1>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="card danger">{err}</div>
{:else if items.length === 0}
  <div class="card">Открытых заявок нет 🎉</div>
{:else}
  {#each items as it (it.id)}
    <section class="card">
      <div class="row">
        <span class="badge" class:bug={it.kind === 'bug'}>
          {it.kind === 'bug' ? '🐞 баг' : '💡 идея'}
        </span>
        <span class="muted small">#{it.id}</span>
        {#if it.created_at}
          <span class="muted small">{it.created_at.slice(0, 16).replace('T', ' ')}</span>
        {/if}
      </div>
      <p class="text">{it.text}</p>
      <div class="ctl">
        <input
          type="number"
          min="0"
          bind:value={amounts[it.id]}
          aria-label="награда"
        />
        <button
          class="ok"
          disabled={busy === it.id}
          on:click={() => close(it, amounts[it.id] ?? 0)}
        >
          {busy === it.id ? '…' : `Закрыть +${amounts[it.id] ?? 0}г`}
        </button>
        <button
          class="zero"
          disabled={busy === it.id}
          on:click={() => close(it, 0)}
        >
          Без награды
        </button>
      </div>
    </section>
  {/each}
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .small { font-size: 12px; }
  .row { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
  .badge {
    font-size: 12px; font-weight: 700; padding: 3px 8px; border-radius: 999px;
    background: var(--accent-soft); color: var(--accent);
  }
  .badge.bug { background: #5b1d1d; color: #ff9a9a; }
  .text { white-space: pre-wrap; line-height: 1.45; margin: 0 0 12px; font-size: 14px; }
  .ctl { display: flex; gap: 8px; align-items: center; }
  input {
    width: 90px; padding: 9px 10px; border: 1px solid var(--separator);
    border-radius: 8px; background: var(--bg); color: var(--text); font-size: 14px;
  }
  button {
    padding: 9px 12px; border: 0; border-radius: 8px; font-weight: 600;
    font-size: 13px; cursor: pointer;
  }
  .ok { background: var(--accent); color: var(--accent-text); flex: 1; }
  .zero { background: var(--bg-elev-2); color: var(--text); }
  button:disabled { opacity: 0.5; }
  .danger { color: #ff9a9a; }
</style>
