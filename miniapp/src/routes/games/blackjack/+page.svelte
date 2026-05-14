<script lang="ts">
  import { onMount } from 'svelte';
  import BetInput from '$lib/BetInput.svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic } from '$lib/tg';
  import type { BalanceResponse, GameResult } from '$lib/types';

  let balance: BalanceResponse | null = null;
  let amount = 100;
  let busy = false;
  let err: string | null = null;
  let game: GameResult | null = null;

  $: active = !!game && game.outcome === 'active';
  $: search = typeof window !== 'undefined' ? window.location.search : '';

  onMount(async () => {
    try {
      balance = await api.balance();
    } catch (e: any) {
      err = e?.message;
    }
  });

  function refreshBalance(r: GameResult) {
    balance = balance && {
      ...balance,
      balance: r.user_balance_after,
      bank: r.bank_after
    };
  }

  async function start() {
    if (busy) return;
    err = null;
    busy = true;
    try {
      game = await api.blackjackStart(amount);
      refreshBalance(game);
      haptic('light');
    } catch (e: any) {
      err = e?.message ?? 'Ошибка';
      haptic('error');
    } finally {
      busy = false;
    }
  }

  async function hit() {
    if (busy || !game) return;
    busy = true;
    try {
      game = await api.blackjackHit(game.game_id);
      refreshBalance(game);
      haptic(game.outcome === 'lose' ? 'error' : game.outcome === 'win' || game.outcome === 'blackjack' ? 'success' : 'light');
    } catch (e: any) {
      err = e?.message;
    } finally {
      busy = false;
    }
  }

  async function stand() {
    if (busy || !game) return;
    busy = true;
    try {
      game = await api.blackjackStand(game.game_id);
      refreshBalance(game);
      haptic(game.outcome === 'win' || game.outcome === 'blackjack' ? 'success' : game.outcome === 'lose' ? 'error' : 'light');
    } catch (e: any) {
      err = e?.message;
    } finally {
      busy = false;
    }
  }

  async function double() {
    if (busy || !game) return;
    busy = true;
    try {
      game = await api.blackjackDouble(game.game_id);
      refreshBalance(game);
      haptic(game.outcome === 'win' ? 'success' : 'error');
    } catch (e: any) {
      err = e?.message;
    } finally {
      busy = false;
    }
  }

  function rankToShort(card: string): string {
    return card.slice(0, -1);
  }
  function suitToSymbol(card: string): string {
    const s = card.slice(-1);
    return { S: '♠', H: '♥', D: '♦', C: '♣' }[s] ?? s;
  }
  function isRed(card: string): boolean {
    return card.endsWith('H') || card.endsWith('D');
  }

  $: playerHand = (game?.details?.player ?? []) as string[];
  $: dealerHand = (game?.details?.dealer ?? game?.details?.dealer_visible
    ? game.details.dealer ?? [game.details.dealer_visible]
    : []) as string[];
  $: dealerHidden = active;
  $: playerTotal = handTotal(playerHand);
  $: dealerTotal = active ? handTotalVisible(dealerHand) : handTotal(dealerHand);

  function handTotalVisible(hand: string[]): number | null {
    if (!hand.length) return null;
    return rankValue(hand[0]);
  }
  function handTotal(hand: string[]): number {
    let total = 0;
    let aces = 0;
    for (const c of hand) {
      const r = c.slice(0, -1);
      if (r === 'A') { total += 11; aces++; }
      else if (['J','Q','K'].includes(r)) total += 10;
      else total += parseInt(r, 10);
    }
    while (total > 21 && aces > 0) { total -= 10; aces--; }
    return total;
  }
  function rankValue(card: string): number {
    const r = card.slice(0, -1);
    if (r === 'A') return 11;
    if (['J','Q','K'].includes(r)) return 10;
    return parseInt(r, 10);
  }

  function outcomeLabel(o: string): string {
    return {
      win: 'Победа',
      lose: 'Поражение',
      push: 'Ничья (push)',
      blackjack: 'BLACKJACK!'
    }[o] ?? o;
  }
</script>

<a class="back" href={`/games${search}`}>← к играм</a>
<h1 class="h1">Blackjack</h1>

{#if balance}
  <div class="bal muted">Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong></div>
{/if}

<section class="card">
  <div class="table">
    <div class="hand-label muted">Дилер · {dealerTotal ?? '?'}</div>
    <div class="hand">
      {#if dealerHand.length}
        {#each dealerHand as card, i}
          <div class="cardv" class:red={isRed(card)}>
            <span class="r">{rankToShort(card)}</span>
            <span class="s">{suitToSymbol(card)}</span>
          </div>
        {/each}
        {#if dealerHidden}
          <div class="cardv hidden">?</div>
        {/if}
      {:else}
        <div class="muted small">—</div>
      {/if}
    </div>

    <div class="hand-label muted" style="margin-top: 18px">Игрок · {playerTotal ?? '?'}</div>
    <div class="hand">
      {#if playerHand.length}
        {#each playerHand as card}
          <div class="cardv" class:red={isRed(card)}>
            <span class="r">{rankToShort(card)}</span>
            <span class="s">{suitToSymbol(card)}</span>
          </div>
        {/each}
      {:else}
        <div class="muted small">Начни новую раздачу</div>
      {/if}
    </div>
  </div>

  {#if active}
    <div class="actions">
      <button class="act hit" disabled={busy} on:click={hit}>Hit</button>
      <button class="act stand" disabled={busy} on:click={stand}>Stand</button>
      {#if game?.details?.can_double && playerHand.length === 2}
        <button class="act double" disabled={busy} on:click={double}>Double</button>
      {/if}
    </div>
  {:else}
    <div class="bet">
      <BetInput bind:amount balance={balance?.balance ?? null} disabled={busy} />
    </div>
    <button class="play" disabled={busy} on:click={start}>
      {busy ? 'Раздаём…' : `Раздача · ставка ${amount}`}
    </button>
  {/if}

  {#if err}
    <div class="danger" style="margin-top: 10px">{err}</div>
  {/if}

  {#if game && !active}
    <div
      class="result"
      class:win={game.outcome === 'win' || game.outcome === 'blackjack'}
      class:lose={game.outcome === 'lose'}
      class:push={game.outcome === 'push'}
    >
      <strong>{outcomeLabel(game.outcome)}.</strong>
      {#if game.net > 0}
        +{fmtCoins(game.net)} в карман.
      {:else if game.net < 0}
        {fmtCoins(game.net)} в банк.
      {:else}
        Ставка возвращена.
      {/if}
    </div>
  {/if}
</section>

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .bal { font-size: 13px; margin-bottom: 12px; }
  .table { margin-bottom: 16px; }
  .hand-label { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px; }
  .hand { display: flex; gap: 8px; flex-wrap: wrap; min-height: 90px; }
  .small { font-size: 13px; }
  .cardv {
    width: 60px; height: 88px;
    background: var(--bg);
    border: 1px solid var(--separator);
    border-radius: 8px;
    display: flex; flex-direction: column; justify-content: space-between;
    padding: 8px 6px;
    color: var(--text);
    font-weight: 700;
    box-shadow: 0 2px 5px rgba(0,0,0,0.08);
  }
  .cardv.red { color: #c1272d; }
  .cardv.hidden {
    background: linear-gradient(135deg, #4a5568, #2d3748);
    color: white;
    align-items: center; justify-content: center;
    font-size: 28px;
  }
  .cardv .r { font-size: 17px; }
  .cardv .s { font-size: 22px; align-self: flex-end; }

  .actions {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(80px, 1fr)); gap: 8px;
    margin-top: 6px;
  }
  .act {
    padding: 13px; border: 0; border-radius: 10px; font-weight: 700; cursor: pointer;
    color: var(--accent-text);
  }
  .act:disabled { opacity: 0.6; }
  .act.hit    { background: var(--accent); }
  .act.stand  { background: var(--text-muted); }
  .act.double { background: var(--positive); }

  .bet { margin-bottom: 14px; }
  .play {
    width: 100%; padding: 14px; background: var(--accent); color: var(--accent-text);
    border: 0; border-radius: 10px; font-weight: 700; font-size: 15px; cursor: pointer;
  }
  .play:disabled { opacity: 0.6; }
  .result {
    margin-top: 14px; padding: 12px; border-radius: 10px; font-size: 14px; text-align: center;
  }
  .result.win { background: var(--positive-soft); color: var(--positive); }
  .result.lose { background: rgba(204, 41, 41, 0.12); color: var(--destructive); }
  .result.push { background: var(--bg-elev-2); }
</style>
