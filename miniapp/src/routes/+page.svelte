<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import type { MeResponse } from '$lib/types';

  let me: MeResponse | null = null;
  let loading = true;
  let err: string | null = null;

  onMount(async () => {
    try {
      me = await api.me();
    } catch (e: any) {
      err = e?.message ?? 'Не удалось загрузить.';
    } finally {
      loading = false;
    }
  });

  const tiles = [
    { href: '/markets', title: 'Рынки', desc: 'Все открытые ставки' },
    { href: '/portfolio', title: 'Портфолио', desc: 'Мои ставки' },
    { href: '/leaderboard', title: 'Лидерборд', desc: 'Топ балансов' },
    { href: '/create', title: 'Создать рынок', desc: 'Любой участник, комиссия 100' },
    { href: '/import', title: 'Импорт рынка', desc: 'polymarket / manifold' }
  ];
</script>

<h1 class="title">xyloz bot</h1>

<section class="card balance">
  {#if loading}
    <div class="hint">Загрузка…</div>
  {:else if err}
    <div class="error">{err}</div>
  {:else if me}
    <div class="user-line">
      {me.user.username ? '@' + me.user.username : me.user.fullname ?? 'Без имени'}
    </div>
    {#if me.balance}
      <div class="big-num">{fmtCoins(me.balance.balance)}</div>
      <div class="hint">коинов на балансе</div>
      <div class="bank">Банк чата: {fmtCoins(me.balance.bank)}</div>
    {:else}
      <div class="hint">chat_id не передан — баланс недоступен</div>
    {/if}
  {/if}
</section>

<section class="tiles">
  {#each tiles as t}
    <a class="tile" href={t.href + (typeof window !== 'undefined' ? window.location.search : '')}>
      <span class="tile-title">{t.title}</span>
      <span class="tile-desc">{t.desc}</span>
    </a>
  {/each}
</section>

<style>
  .title {
    font-size: 22px;
    margin: 4px 0 16px;
  }
  .card {
    background: var(--section-bg);
    padding: 18px;
    border-radius: 14px;
    margin-bottom: 16px;
  }
  .user-line {
    font-size: 13px;
    color: var(--hint);
    margin-bottom: 6px;
  }
  .big-num {
    font-size: 38px;
    font-weight: 600;
    line-height: 1.1;
  }
  .hint {
    color: var(--hint);
    font-size: 13px;
  }
  .bank {
    margin-top: 12px;
    font-size: 13px;
    color: var(--hint);
  }
  .error {
    color: var(--destructive);
  }
  .tiles {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .tile {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 14px;
    background: var(--section-bg);
    border-radius: 12px;
    color: var(--text);
  }
  .tile-title {
    font-weight: 600;
  }
  .tile-desc {
    font-size: 12px;
    color: var(--hint);
  }
</style>
