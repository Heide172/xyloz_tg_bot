<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import type { BalanceResponse, MeResponse } from '$lib/types';

  let me: MeResponse | null = null;
  let balance: BalanceResponse | null = null;
  let err: string | null = null;

  onMount(async () => {
    try {
      me = await api.me();
      if (me.balance) balance = me.balance;
    } catch (e: any) {
      err = e?.message;
    }
  });

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  const items = [
    { href: 'balance', title: 'Баланс юзера', desc: 'Прибавить/списать гривны участнику' },
    { href: 'bank', title: 'Банк чата', desc: 'Корректировать общий банк' },
    { href: 'markets/manage', title: 'Управление рынками', desc: 'Resolve / Cancel' }
  ];
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Админка</h1>

{#if err}
  <div class="danger">{err}</div>
{:else if me && !me.is_admin}
  <div class="card danger">
    У тебя нет прав. (tg_id <strong>{me.user.tg_id}</strong> не в BOT_ADMIN_IDS).
  </div>
{:else if me}
  {#if balance}
    <div class="bal-strip card">
      <span class="muted">Банк чата:</span>
      <strong>{fmtCoins(balance.bank)}</strong>
    </div>
  {/if}
  <div class="grid">
    {#each items as it}
      <a class="tile" href={`/admin/${it.href}${search}`}>
        <span class="t">{it.title}</span>
        <span class="d muted">{it.desc}</span>
      </a>
    {/each}
  </div>
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .bal-strip {
    display: flex; gap: 6px; align-items: baseline; margin-bottom: 14px; padding: 12px 14px;
  }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .tile {
    background: var(--bg-elev); border-radius: 14px; padding: 16px; color: var(--text);
    display: flex; flex-direction: column; gap: 4px; box-shadow: var(--shadow);
  }
  .t { font-weight: 600; font-size: 15px; }
  .d { font-size: 12px; line-height: 1.4; }
</style>
