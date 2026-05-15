<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';
  import UserPicker from '$lib/UserPicker.svelte';
  import type { BalanceResponse } from '$lib/types';

  let balance: BalanceResponse | null = null;
  let data: any = { incoming: [], outgoing: [], history: [], me: 0 };
  let loading = true;
  let err: string | null = null;
  let busy = false;

  let opponent = '';
  let stake = 100;

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  async function refresh() {
    try {
      [balance, data] = await Promise.all([api.balance(), api.duelList()]);
    } catch (e: any) {
      err = e?.message;
    } finally {
      loading = false;
    }
  }
  onMount(refresh);

  async function challenge() {
    if (busy) return;
    if (!opponent.trim()) return showAlert('Кого вызвать?');
    if (stake < 10) return showAlert('Минимум 10');
    busy = true;
    try {
      await api.duelChallenge(opponent.trim(), stake);
      haptic('success');
      opponent = '';
      await refresh();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busy = false;
    }
  }

  async function act(fn: () => Promise<any>, win?: boolean) {
    if (busy) return;
    busy = true;
    try {
      const r = await fn();
      if (r && typeof r.you_won === 'boolean') {
        haptic(r.you_won ? 'success' : 'error');
        showAlert(
          r.you_won
            ? `Победа! +${fmtCoins(r.prize)} (комиссия ${fmtCoins(r.commission)})`
            : `Поражение. Дуэль #${r.id} проиграна.`
        );
      } else {
        haptic('light');
      }
      await refresh();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busy = false;
    }
  }
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Дуэль 1v1</h1>

{#if balance}
  <div class="bal muted">
    Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong>
  </div>
{/if}

<section class="card">
  <div class="t">Вызвать на дуэль</div>
  <p class="muted small">Оба ставят X. Победитель (50/50) забирает 2X − 5% (комиссия в банк).</p>
  <UserPicker bind:value={opponent} placeholder="@username соперника" />
  <div class="stake-row">
    <input type="number" min="10" step="10" bind:value={stake} />
    <span class="muted small">ставка</span>
    {#each [50, 100, 500] as p}
      <button class="preset" on:click={() => (stake = p)}>{p}</button>
    {/each}
  </div>
  <button class="go" disabled={busy} on:click={challenge}>
    {busy ? '…' : `Вызвать · ставка ${fmtCoins(stake)}`}
  </button>
</section>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else}
  {#if data.incoming.length}
    <div class="sec-title">Тебя вызвали</div>
    {#each data.incoming as d}
      <div class="card duel">
        <div class="d-info">
          <strong>{d.challenger}</strong> вызвал на {fmtCoins(d.stake)}
        </div>
        <div class="d-act">
          <button class="accept" disabled={busy} on:click={() => act(() => api.duelAccept(d.id))}>
            Принять
          </button>
          <button class="decline" disabled={busy} on:click={() => act(() => api.duelDecline(d.id))}>
            Отклонить
          </button>
        </div>
      </div>
    {/each}
  {/if}

  {#if data.outgoing.length}
    <div class="sec-title">Твои вызовы</div>
    {#each data.outgoing as d}
      <div class="card duel">
        <div class="d-info">
          → <strong>{d.opponent}</strong>, ставка {fmtCoins(d.stake)} · ждём ответа
        </div>
        <button class="decline" disabled={busy} on:click={() => act(() => api.duelCancel(d.id))}>
          Отменить
        </button>
      </div>
    {/each}
  {/if}

  {#if data.history.length}
    <div class="sec-title">История</div>
    <div class="card list">
      {#each data.history as d}
        <div class="hrow">
          <span class="hnm">{d.challenger} vs {d.opponent}</span>
          <span class="hres muted">
            {#if d.status === 'resolved'}
              {d.winner_id === data.me ? '✅ ты выиграл' : 'проигрыш'} · {fmtCoins(d.stake)}
            {:else}
              {d.status === 'declined' ? 'отклонён' : 'отменён'}
            {/if}
          </span>
        </div>
      {/each}
    </div>
  {/if}

  {#if !data.incoming.length && !data.outgoing.length && !data.history.length}
    <div class="muted" style="margin-top:12px">Дуэлей пока нет — вызови кого-нибудь.</div>
  {/if}
{/if}

{#if err}
  <div class="danger" style="margin-top:10px">{err}</div>
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .bal { font-size: 13px; margin-bottom: 12px; }
  .small { font-size: 12px; }
  .t { font-weight: 700; font-size: 15px; margin-bottom: 4px; }
  .card { margin-bottom: 12px; }
  .stake-row {
    display: flex;
    gap: 6px;
    align-items: center;
    flex-wrap: wrap;
    margin: 10px 0;
  }
  .stake-row input {
    flex: 0 0 90px;
    padding: 9px 10px;
    border: 1px solid var(--separator);
    border-radius: 8px;
    background: var(--bg);
    color: var(--text);
    font-size: 15px;
  }
  .preset {
    padding: 7px 10px;
    border: 0;
    background: var(--bg-elev-2);
    color: var(--text);
    border-radius: 7px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  .go {
    width: 100%;
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
  .sec-title {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin: 16px 0 8px;
  }
  .duel { display: flex; flex-direction: column; gap: 10px; }
  .d-info { font-size: 14px; }
  .d-act { display: flex; gap: 8px; }
  .accept, .decline {
    flex: 1;
    padding: 10px;
    border: 0;
    border-radius: 9px;
    font-weight: 700;
    font-size: 13px;
    cursor: pointer;
  }
  .accept { background: var(--positive); color: #fff; }
  .decline { background: var(--bg-elev-2); color: var(--text); }
  .accept:disabled, .decline:disabled { opacity: 0.6; }
  .list { padding: 4px 0; }
  .hrow {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    padding: 8px 14px;
    border-bottom: 1px solid var(--separator);
    font-size: 13px;
  }
  .hrow:last-child { border-bottom: 0; }
  .hnm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hres { font-size: 12px; white-space: nowrap; }
</style>
