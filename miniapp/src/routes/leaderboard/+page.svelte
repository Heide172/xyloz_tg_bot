<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';

  type Player = {
    tg_id: number;
    username: string | null;
    fullname: string | null;
    balance: number;
    casino_net: number;
    casino_staked: number;
    casino_won: number;
    farm_earned: number;
    games_played: number;
  };
  type BigWin = {
    username: string | null;
    fullname: string | null;
    game: string;
    bet: number;
    payout: number;
    created_at: string;
  };

  let players: Player[] = [];
  let bigWins: BigWin[] = [];
  let loading = true;
  let err: string | null = null;
  type Tab = 'balance' | 'casino' | 'farm' | 'wins';
  let tab: Tab = 'balance';

  onMount(async () => {
    try {
      const d = await api.stats();
      players = d.players;
      bigWins = d.biggest_wins;
    } catch (e: any) {
      err = e?.message ?? 'Не удалось загрузить';
    } finally {
      loading = false;
    }
  });

  function name(p: { username: string | null; fullname: string | null }): string {
    if (p.username) return '@' + p.username;
    return p.fullname ?? 'Unknown';
  }

  const GAME_RU: Record<string, string> = {
    slots: 'Slots',
    roulette: 'Рулетка',
    blackjack: 'Blackjack',
    coinflip: 'Coinflip',
    dice: 'Dice'
  };

  $: byBalance = [...players].sort((a, b) => b.balance - a.balance);
  $: byCasino = [...players]
    .filter((p) => p.games_played > 0)
    .sort((a, b) => b.casino_net - a.casino_net);
  $: byFarm = [...players]
    .filter((p) => p.farm_earned > 0)
    .sort((a, b) => b.farm_earned - a.farm_earned);

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  function rankClass(i: number): string {
    return i === 0 ? 'gold' : i === 1 ? 'silver' : i === 2 ? 'bronze' : '';
  }
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Статистика</h1>

<div class="tabs">
  <button class="tab" class:active={tab === 'balance'} on:click={() => (tab = 'balance')}>Баланс</button>
  <button class="tab" class:active={tab === 'casino'} on:click={() => (tab = 'casino')}>Казино</button>
  <button class="tab" class:active={tab === 'farm'} on:click={() => (tab = 'farm')}>Ферма</button>
  <button class="tab" class:active={tab === 'wins'} on:click={() => (tab = 'wins')}>Биг-вины</button>
</div>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="danger">{err}</div>
{:else if tab === 'balance'}
  <div class="list card">
    {#each byBalance as p, i}
      <div class="row">
        <span class="rank {rankClass(i)}">{i + 1}</span>
        <span class="nm">{name(p)}</span>
        <span class="val">{fmtCoins(p.balance)}</span>
      </div>
    {/each}
  </div>
{:else if tab === 'casino'}
  {#if byCasino.length === 0}
    <div class="muted">Ещё никто не играл.</div>
  {:else}
    <div class="list card">
      {#each byCasino as p, i}
        <div class="row casino">
          <span class="rank {rankClass(i)}">{i + 1}</span>
          <div class="nm-col">
            <span class="nm">{name(p)}</span>
            <span class="sub muted">
              {p.games_played} игр · ставок {fmtCoins(p.casino_staked)}
            </span>
          </div>
          <span class="val" class:pos={p.casino_net > 0} class:neg={p.casino_net < 0}>
            {p.casino_net > 0 ? '+' : ''}{fmtCoins(p.casino_net)}
          </span>
        </div>
      {/each}
    </div>
  {/if}
{:else if tab === 'farm'}
  {#if byFarm.length === 0}
    <div class="muted">Ферма ещё не приносила гривны.</div>
  {:else}
    <div class="list card">
      {#each byFarm as p, i}
        <div class="row">
          <span class="rank {rankClass(i)}">{i + 1}</span>
          <span class="nm">{name(p)}</span>
          <span class="val pos">+{fmtCoins(p.farm_earned)}</span>
        </div>
      {/each}
    </div>
  {/if}
{:else if tab === 'wins'}
  {#if bigWins.length === 0}
    <div class="muted">Крупных выигрышей пока нет.</div>
  {:else}
    <div class="list card">
      {#each bigWins as w, i}
        <div class="row win">
          <span class="rank {rankClass(i)}">{i + 1}</span>
          <div class="nm-col">
            <span class="nm">{name(w)}</span>
            <span class="sub muted">{GAME_RU[w.game] ?? w.game} · ставка {fmtCoins(w.bet)}</span>
          </div>
          <span class="val pos">+{fmtCoins(w.payout - w.bet)}</span>
        </div>
      {/each}
    </div>
  {/if}
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .tabs {
    display: flex;
    gap: 5px;
    background: var(--bg-elev);
    padding: 4px;
    border-radius: 11px;
    margin-bottom: 14px;
  }
  .tab {
    flex: 1;
    padding: 8px 4px;
    border: 0;
    background: transparent;
    color: var(--text-muted);
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  .tab.active {
    background: var(--bg);
    color: var(--text);
    box-shadow: var(--shadow);
  }
  .list { overflow: hidden; }
  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--separator);
  }
  .row:last-child { border-bottom: 0; }
  .rank {
    flex: 0 0 28px;
    width: 28px;
    height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: var(--bg-elev-2);
    font-variant-numeric: tabular-nums;
    font-weight: 700;
    font-size: 13px;
    color: var(--text-muted);
  }
  .rank.gold { background: #f7d147; color: #5b3e00; }
  .rank.silver { background: #d3d6db; color: #2f3033; }
  .rank.bronze { background: #d49a64; color: #4a2a07; }
  .nm-col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
  .nm {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
    font-size: 14px;
  }
  .sub { font-size: 11px; }
  .val {
    font-variant-numeric: tabular-nums;
    font-weight: 700;
    font-size: 14px;
  }
  .val.pos { color: var(--positive); }
  .val.neg { color: var(--destructive); }
</style>
