<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import type { BalanceResponse } from '$lib/types';

  let balance: BalanceResponse | null = null;

  onMount(async () => {
    try {
      balance = await api.balance();
    } catch {
      /* may be missing chat_id */
    }
  });

  const games = [
    { href: 'coinflip',  title: 'Coinflip',  desc: 'Орёл или решка, 1.98x' },
    { href: 'dice',      title: 'Dice',      desc: 'Бросок 1-100, мультипликатор зависит от шанса' },
    { href: 'slots',     title: 'Slots',     desc: 'Три барабана, до 50x' },
    { href: 'blackjack', title: 'Blackjack', desc: 'Очко: hit / stand / double, BJ платит 2.5x' },
    { href: 'roulette',  title: 'Roulette',  desc: 'European: 0-36, до 36x' }
  ];

  $: search = typeof window !== 'undefined' ? window.location.search : '';
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Игры</h1>

{#if balance}
  <div class="bal-strip card">
    <span class="muted">Баланс:</span>
    <strong>{fmtCoins(balance.balance)}</strong>
    <span class="muted" style="margin-left: auto">Банк: {fmtCoins(balance.bank)}</span>
  </div>
{/if}

<div class="grid">
  {#each games as g}
    <a class="game-card" href={`/games/${g.href}${search}`}>
      <span class="title">{g.title}</span>
      <span class="desc muted">{g.desc}</span>
    </a>
  {/each}
</div>

<style>
  .back {
    display: inline-block;
    margin-bottom: 8px;
    font-size: 14px;
    color: var(--text-muted);
  }
  .bal-strip {
    display: flex;
    align-items: baseline;
    gap: 6px;
    margin-bottom: 14px;
    padding: 12px 14px;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .game-card {
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
  .game-card:active {
    transform: scale(0.97);
  }
  .game-card:nth-child(5) {
    grid-column: 1 / -1;
  }
  .title {
    font-weight: 600;
    font-size: 15px;
  }
  .desc {
    font-size: 12px;
    line-height: 1.4;
  }
</style>
