<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { balanceStore } from '$lib/balance';
  import { fmtCoins } from '$lib/format';
  import { CHANGELOG } from '$lib/changelog';
  import type { MeResponse } from '$lib/types';

  let me: MeResponse | null = null;
  let loading = true;
  let err: string | null = null;
  let hasNew = false;

  // Лёгкий статус тега для баннера «истекает».
  let tagMine: { title: string; expires_at: string; expired: boolean } | null = null;

  function utcDate(s: string): Date {
    return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z');
  }

  $: tagSoon = (() => {
    if (!tagMine) return false;
    if (tagMine.expired) return true;
    const ms = utcDate(tagMine.expires_at).getTime() - Date.now();
    return ms > 0 && ms < 24 * 3600 * 1000;
  })();
  $: tagHoursLeft = (() => {
    if (!tagMine || tagMine.expired) return null;
    const ms = utcDate(tagMine.expires_at).getTime() - Date.now();
    if (ms <= 0) return 0;
    return Math.max(1, Math.round(ms / 3600 / 1000));
  })();

  onMount(async () => {
    try {
      const seen = localStorage.getItem('cl_seen') ?? '';
      hasNew = !!CHANGELOG[0] && CHANGELOG[0].date > seen;
    } catch {
      /* ignore */
    }
    const [meRes, tagRes] = await Promise.allSettled([
      api.me(),
      api.tagsState()
    ]);
    if (meRes.status === 'fulfilled') me = meRes.value;
    else err = (meRes.reason as any)?.message ?? 'Не удалось загрузить.';
    if (tagRes.status === 'fulfilled') tagMine = tagRes.value?.mine ?? null;
    loading = false;
  });

  $: baseTiles = [
    { href: '/farm', title: 'Ферма', desc: 'Тапай, копи cp, выводи в гривны' },
    { href: '/gacha', title: 'Гача', desc: 'Крути девочек, собирай коллекцию' },
    { href: '/markets', title: 'Рынки', desc: 'Открытые ставки' },
    { href: '/games', title: 'Игры', desc: 'Blackjack, slots, дайс, рулетка' },
    { href: '/shop', title: 'Магазин', desc: 'Прожарка, анекдот, пнуть' },
    { href: '/duel', title: 'Дуэль', desc: '1v1 на гривны' },
    { href: '/tags', title: 'Теги', desc: 'Аренда подписи в чате' },
    { href: '/transfer', title: 'Перевод', desc: 'Отправить гривны (комиссия 5%)' },
    { href: '/portfolio', title: 'Портфолио', desc: 'Мои ставки' },
    { href: '/leaderboard', title: 'Статистика', desc: 'Баланс, казино, ферма, биг-вины' },
    { href: '/history', title: 'История', desc: 'Лента событий чата' },
    { href: '/rules', title: 'Правила', desc: 'Как это работает' },
    {
      href: '/changelog',
      title: hasNew ? 'Что нового ●' : 'Что нового',
      desc: hasNew ? 'Есть свежие обновления' : 'Список изменений'
    },
    { href: '/feedback', title: 'Обратная связь', desc: 'Баг или идея' },
    {
      href: 'https://xn--b1afabzvcegckfhg.xn--p1ai/',
      title: 'Поддержка по VPN',
      desc: 'Помощь с доступом',
      external: true
    }
  ];
  $: tiles = me?.is_admin
    ? [...baseTiles, { href: '/admin', title: 'Админка', desc: 'Управление' }]
    : baseTiles;

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
        {fmtCoins($balanceStore.balance ?? me.balance.balance)}
        <span class="big-suf muted">гривен</span>
      </div>
      <div class="bank-line">
        <span class="muted">Банк чата:</span>
        <strong>{fmtCoins($balanceStore.bank ?? me.balance.bank)}</strong>
      </div>
    {:else}
      <div class="muted">chat_id не передан — баланс недоступен</div>
    {/if}
  {/if}
</section>

{#if tagSoon && tagMine}
  <a
    class="tag-banner"
    class:warn={tagMine.expired}
    href={`/tags${typeof window !== 'undefined' ? window.location.search : ''}`}
  >
    <div class="tb-head">
      {#if tagMine.expired}
        ⌛ Тег «{tagMine.title}» истёк
      {:else}
        ⏰ Тег «{tagMine.title}» истекает через ~{tagHoursLeft}ч
      {/if}
    </div>
    <div class="tb-cta">Продлить →</div>
  </a>
{/if}

<section class="tiles">
  {#each tiles as t}
    {#if t.external}
      <a class="tile" href={t.href} target="_blank" rel="noopener noreferrer">
        <span class="tile-title">{t.title}</span>
        <span class="tile-desc muted">{t.desc}</span>
      </a>
    {:else}
      <a class="tile" href={t.href + (typeof window !== 'undefined' ? window.location.search : '')}>
        <span class="tile-title">{t.title}</span>
        <span class="tile-desc muted">{t.desc}</span>
      </a>
    {/if}
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

  .tag-banner {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    margin-bottom: 14px;
    border: 1px solid var(--accent);
    background: var(--accent-soft);
    border-radius: 12px;
    color: var(--text);
    text-decoration: none;
    box-shadow: var(--shadow);
  }
  .tag-banner.warn {
    border-color: #c87a2a;
    background: rgba(200, 122, 42, 0.12);
  }
  .tb-head { font-weight: 700; font-size: 14px; }
  .tb-cta {
    font-weight: 700; font-size: 13px;
    color: var(--accent); white-space: nowrap;
  }
  .tag-banner.warn .tb-cta { color: #c87a2a; }
</style>
