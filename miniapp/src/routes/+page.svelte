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
    { href: '/markets', title: 'Рынки', desc: 'Открытые ставки' },
    { href: '/games', title: 'Игры', desc: 'Blackjack, slots, дайс, рулетка' },
    { href: '/portfolio', title: 'Портфолио', desc: 'Мои ставки' },
    { href: '/leaderboard', title: 'Топ', desc: 'Лидерборд чата' },
    { href: '/rules', title: 'Правила', desc: 'Как это работает' }
  ];

  function displayName(m: MeResponse): string {
    if (m.user.username) return '@' + m.user.username;
    if (m.user.fullname) return m.user.fullname;
    return 'Без имени';
  }
</script>

<h1 class="h1">Бурмалда</h1>

<section class="balance-card">
  {#if loading}
    <div class="loading-line" style="width: 60%"></div>
    <div class="loading-line big" style="width: 50%; margin-top: 14px"></div>
    <div class="loading-line" style="width: 40%; margin-top: 8px"></div>
  {:else if err}
    <div class="danger">{err}</div>
  {:else if me}
    <div class="user-line muted">{displayName(me)}</div>
    {#if me.balance}
      <div class="big-num">
        {fmtCoins(me.balance.balance)}
        <span class="big-suf muted">гривен</span>
      </div>
      <div class="bank-line">
        <span class="muted">Банк чата:</span>
        <strong>{fmtCoins(me.balance.bank)}</strong>
      </div>
    {:else}
      <div class="muted">chat_id не передан — баланс недоступен</div>
    {/if}
  {/if}
</section>

<section class="tiles">
  {#each tiles as t}
    <a class="tile" href={t.href + (typeof window !== 'undefined' ? window.location.search : '')}>
      <span class="tile-title">{t.title}</span>
      <span class="tile-desc muted">{t.desc}</span>
    </a>
  {/each}
</section>

<style>
  .balance-card {
    background: linear-gradient(135deg, var(--accent) 0%, color-mix(in srgb, var(--accent) 75%, #000) 100%);
    color: var(--accent-text);
    padding: 22px 20px;
    border-radius: 18px;
    margin-bottom: 18px;
    box-shadow: var(--shadow);
  }
  .balance-card :global(.muted) {
    color: color-mix(in srgb, var(--accent-text) 75%, transparent);
  }
  .user-line {
    font-size: 13px;
    margin-bottom: 4px;
  }
  .big-num {
    font-size: 42px;
    font-weight: 700;
    line-height: 1.05;
    letter-spacing: -0.02em;
  }
  .big-suf {
    font-size: 14px;
    font-weight: 500;
    margin-left: 6px;
  }
  .bank-line {
    margin-top: 14px;
    font-size: 13px;
    display: flex;
    gap: 6px;
  }

  .tiles {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .tile {
    background: var(--bg-elev);
    border-radius: 14px;
    padding: 16px;
    color: var(--text);
    display: flex;
    flex-direction: column;
    gap: 4px;
    box-shadow: var(--shadow);
    transition: transform 0.15s ease;
  }
  .tile:active {
    transform: scale(0.97);
  }
  .tile-title {
    font-weight: 600;
    font-size: 15px;
  }
  .tile-desc {
    font-size: 12px;
  }

  .loading-line {
    height: 14px;
    border-radius: 6px;
    background: color-mix(in srgb, var(--accent-text) 25%, transparent);
  }
  .loading-line.big {
    height: 32px;
  }
</style>
