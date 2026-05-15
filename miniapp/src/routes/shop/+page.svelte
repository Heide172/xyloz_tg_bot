<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';
  import UserPicker from '$lib/UserPicker.svelte';
  import type { BalanceResponse } from '$lib/types';

  let balance: BalanceResponse | null = null;
  let prices = { poke: 50, joke: 150, roast: 300 };
  let busy = '';
  let err: string | null = null;
  let lastResult: string | null = null;

  let pokeTarget = '';
  let pokeKind: 'poke' | 'hug' | 'highfive' = 'poke';
  let jokeTopic = '';
  let roastTarget = '';

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  onMount(async () => {
    try {
      [balance, prices] = await Promise.all([api.balance(), api.shopPrices()]);
    } catch (e: any) {
      err = e?.message;
    }
  });

  function applyResult(r: { text: string; user_balance: number }) {
    if (balance) balance = { ...balance, balance: r.user_balance };
    lastResult = r.text;
    haptic('success');
  }

  async function doPoke() {
    if (busy) return;
    if (!pokeTarget.trim()) return showAlert('Кого?');
    busy = 'poke';
    try {
      applyResult(await api.shopPoke(pokeTarget.trim(), pokeKind));
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busy = '';
    }
  }

  async function doJoke() {
    if (busy) return;
    if (jokeTopic.trim().length < 2) return showAlert('Тема?');
    busy = 'joke';
    try {
      applyResult(await api.shopJoke(jokeTopic.trim()));
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busy = '';
    }
  }

  async function doRoast() {
    if (busy) return;
    if (!roastTarget.trim()) return showAlert('Кого прожарить?');
    busy = 'roast';
    try {
      applyResult(await api.shopRoast(roastTarget.trim()));
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busy = '';
    }
  }
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Магазин</h1>

{#if balance}
  <div class="bal muted">
    Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong>
  </div>
{/if}
<p class="muted small sub">Действие постится в чат. Оплата уходит в банк чата.</p>

<section class="card item">
  <div class="head">
    <span class="t">Пнуть / обнять</span>
    <span class="price">{fmtCoins(prices.poke)}</span>
  </div>
  <div class="kinds">
    {#each [['poke', 'Пнуть'], ['hug', 'Обнять'], ['highfive', 'Дать пять']] as [k, lbl]}
      <button class="kind" class:active={pokeKind === k} on:click={() => (pokeKind = k)}>
        {lbl}
      </button>
    {/each}
  </div>
  <UserPicker bind:value={pokeTarget} placeholder="кого" />
  <button class="go" disabled={busy === 'poke'} on:click={doPoke}>
    {busy === 'poke' ? 'Шлём…' : `Отправить · ${fmtCoins(prices.poke)}`}
  </button>
</section>

<section class="card item">
  <div class="head">
    <span class="t">Анекдот на заказ</span>
    <span class="price">{fmtCoins(prices.joke)}</span>
  </div>
  <input class="inp" placeholder="тема анекдота" bind:value={jokeTopic} />
  <button class="go" disabled={busy === 'joke'} on:click={doJoke}>
    {busy === 'joke' ? 'Сочиняем…' : `Заказать · ${fmtCoins(prices.joke)}`}
  </button>
</section>

<section class="card item">
  <div class="head">
    <span class="t">🔥 AI-прожарка</span>
    <span class="price">{fmtCoins(prices.roast)}</span>
  </div>
  <p class="muted small">Бот зло, но по-доброму подколет игрока в чате.</p>
  <UserPicker bind:value={roastTarget} placeholder="кого прожарить" />
  <button class="go" disabled={busy === 'roast'} on:click={doRoast}>
    {busy === 'roast' ? 'Жарим…' : `Прожарить · ${fmtCoins(prices.roast)}`}
  </button>
</section>

{#if lastResult}
  <div class="result card">
    <div class="muted small" style="margin-bottom:4px">Отправлено в чат:</div>
    {lastResult}
  </div>
{/if}
{#if err}
  <div class="danger" style="margin-top:10px">{err}</div>
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .bal { font-size: 13px; }
  .sub { margin: 4px 0 14px; }
  .small { font-size: 12px; }
  .item { margin-bottom: 12px; }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 10px;
  }
  .t { font-weight: 700; font-size: 15px; }
  .price {
    font-variant-numeric: tabular-nums;
    font-weight: 700;
    color: var(--accent);
  }
  .kinds { display: flex; gap: 6px; margin-bottom: 10px; }
  .kind {
    flex: 1;
    padding: 8px;
    border: 1px solid var(--separator);
    background: var(--bg);
    color: var(--text);
    border-radius: 8px;
    font-size: 13px;
    cursor: pointer;
  }
  .kind.active { border-color: var(--accent); background: var(--accent-soft); }
  .inp {
    width: 100%;
    padding: 11px 12px;
    border: 1px solid var(--separator);
    border-radius: 9px;
    font-size: 16px;
    background: var(--bg);
    color: var(--text);
    margin-bottom: 10px;
  }
  .go {
    width: 100%;
    margin-top: 10px;
    padding: 12px;
    background: var(--accent);
    color: var(--accent-text);
    border: 0;
    border-radius: 10px;
    font-weight: 700;
    font-size: 14px;
    cursor: pointer;
  }
  .go:disabled { opacity: 0.6; }
  .result {
    margin-top: 6px;
    font-size: 14px;
    line-height: 1.5;
    white-space: pre-wrap;
  }
</style>
