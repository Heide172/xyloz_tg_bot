<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import type { HistoryItem } from '$lib/types';

  let items: HistoryItem[] = [];
  let loading = true;
  let err: string | null = null;
  let offset = 0;
  let hasMore = false;
  let loadingMore = false;
  const PAGE = 50;

  // kind → человекочитаемая категория + знак-нейтральная подпись
  const KIND_LABEL: Record<string, string> = {
    start_bonus: 'Стартовый бонус',
    transfer: 'Перевод',
    admin_adjust: 'Корректировка админом',
    admin_bank_adjust: 'Банк: корректировка',
    admin_bank_seed: 'Банк: пополнение',
    market_create_fee_user: 'Создание рынка (комиссия)',
    market_import_fee_user: 'Импорт рынка (комиссия)',
    market_bet: 'Ставка на рынок',
    market_payout: 'Выплата по рынку',
    market_commission: 'Комиссия рынка',
    market_refund: 'Возврат ставки',
    casino_coinflip_bet: 'Coinflip: ставка',
    casino_coinflip_payout: 'Coinflip: выигрыш',
    casino_dice_bet: 'Dice: ставка',
    casino_dice_payout: 'Dice: выигрыш',
    casino_slots_bet: 'Slots: ставка',
    casino_slots_payout: 'Slots: выигрыш',
    casino_roulette_bet: 'Рулетка: ставка',
    casino_roulette_payout: 'Рулетка: выигрыш',
    casino_blackjack_bet: 'Blackjack: ставка',
    casino_blackjack_double: 'Blackjack: удвоение',
    casino_blackjack_payout: 'Blackjack: выигрыш',
    clicker_convert_to_user: 'Ферма → гривны',
    nomination: 'Номинация дня'
  };

  function label(k: string): string {
    if (KIND_LABEL[k]) return KIND_LABEL[k];
    if (k.startsWith('nomination')) return 'Номинация дня';
    return k;
  }

  function who(it: HistoryItem): string {
    if (it.username) return '@' + it.username;
    if (it.fullname) return it.fullname;
    return it.user_id ? `user #${it.user_id}` : 'система';
  }

  function fmtTime(iso: string): string {
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  async function loadPage(reset = false) {
    if (reset) {
      offset = 0;
      items = [];
    }
    try {
      const data = await api.history(PAGE, offset);
      items = [...items, ...data.items];
      hasMore = data.has_more;
      offset += data.items.length;
    } catch (e: any) {
      err = e?.message ?? 'Не удалось загрузить';
    } finally {
      loading = false;
      loadingMore = false;
    }
  }

  onMount(() => loadPage(true));

  async function more() {
    if (loadingMore || !hasMore) return;
    loadingMore = true;
    await loadPage();
  }

  $: search = typeof window !== 'undefined' ? window.location.search : '';
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">История</h1>
<p class="muted small sub">Лента всех денежных событий чата — для прозрачности.</p>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="danger">{err}</div>
{:else if items.length === 0}
  <div class="muted">Пока пусто.</div>
{:else}
  <div class="feed card">
    {#each items as it (it.id)}
      <div class="row">
        <div class="main">
          <span class="who">{who(it)}</span>
          <span class="kind muted">{label(it.kind)}</span>
          {#if it.note}
            <span class="note muted">· {it.note}</span>
          {/if}
        </div>
        <div class="meta">
          <span class="amt" class:pos={it.amount > 0} class:neg={it.amount < 0}>
            {it.amount > 0 ? '+' : ''}{fmtCoins(it.amount)}
          </span>
          <span class="time muted">{fmtTime(it.created_at)}</span>
        </div>
      </div>
    {/each}
  </div>

  {#if hasMore}
    <button class="more" on:click={more} disabled={loadingMore}>
      {loadingMore ? 'Загрузка…' : 'Показать ещё'}
    </button>
  {/if}
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .sub { margin: -8px 0 14px; }
  .small { font-size: 12px; }
  .feed { padding: 4px 0; }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--separator);
  }
  .row:last-child { border-bottom: 0; }
  .main { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
  .who { font-weight: 600; font-size: 14px; }
  .kind { font-size: 12px; }
  .note {
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 220px;
  }
  .meta { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
  .amt {
    font-variant-numeric: tabular-nums;
    font-weight: 700;
    font-size: 14px;
  }
  .amt.pos { color: var(--positive); }
  .amt.neg { color: var(--destructive); }
  .time { font-size: 11px; white-space: nowrap; }
  .more {
    width: 100%;
    margin-top: 12px;
    padding: 12px;
    background: var(--bg-elev);
    color: var(--text);
    border: 0;
    border-radius: 10px;
    font-weight: 600;
    cursor: pointer;
  }
  .more:disabled { opacity: 0.6; }
</style>
