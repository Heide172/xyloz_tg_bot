<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';
  import UserPicker from '$lib/UserPicker.svelte';
  import type { BalanceResponse } from '$lib/types';

  let balance: BalanceResponse | null = null;
  let st: any = null;
  let loading = true;
  let err: string | null = null;
  let busy = false;

  let title = '';
  let days = 1;
  let giftOpen = false;
  let giftTo = '';

  // Предупреждение, если последний rent/cancel/reapply не выставил Telegram-тег
  let tgWarn: string | null = null;
  let reapplyBusy = false;

  $: search = typeof window !== 'undefined' ? window.location.search : '';
  $: price = st ? st.per_day * days : 0;
  $: titleTaken =
    st && title.trim() && st.occupied.includes(title.trim()) && st.mine?.title !== title.trim();

  // «Скоро истечёт» = осталось < 24ч; «Истёк» = expired=true.
  $: expSoon = (() => {
    if (!st?.mine) return false;
    if (st.mine.expired) return true;
    const ms = new Date(st.mine.expires_at).getTime() - Date.now();
    return ms > 0 && ms < 24 * 3600 * 1000;
  })();

  $: hoursLeft = (() => {
    if (!st?.mine || st.mine.expired) return null;
    const ms = new Date(st.mine.expires_at).getTime() - Date.now();
    if (ms <= 0) return 0;
    return Math.max(1, Math.round(ms / 3600 / 1000));
  })();

  let extendBusy = false;

  async function extend(d: number) {
    if (extendBusy || !st?.mine) return;
    const t = st.mine.title;
    extendBusy = true;
    tgWarn = null;
    try {
      const r = await api.tagsRent(t, d, null);
      if (balance) balance = { ...balance, balance: r.user_balance };
      haptic(r.tg_applied ? 'success' : 'error');
      if (r.tg_applied) {
        showAlert(
          `Тег «${r.title}» продлён на ${d} дн., до ${new Date(r.expires_at).toLocaleString('ru-RU')}.`
        );
      } else {
        tgWarn = r.tg_error ?? 'Telegram не подтвердил установку тега.';
      }
      if (st) {
        st = { ...st, mine: { title: r.title, expires_at: r.expires_at, expired: false } };
      }
      await refresh();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      extendBusy = false;
    }
  }

  async function refresh() {
    try {
      [balance, st] = await Promise.all([api.balance(), api.tagsState()]);
    } catch (e: any) {
      err = e?.message;
    } finally {
      loading = false;
    }
  }
  onMount(refresh);

  async function rent() {
    if (busy) return;
    const t = title.trim();
    if (!t) return showAlert('Введи текст тега');
    if (t.length > (st?.max_len ?? 16)) return showAlert(`Максимум ${st.max_len} символов`);
    const gift = giftOpen ? giftTo.trim() : null;
    if (giftOpen && !gift) return showAlert('Выбери получателя или закрой подарок');
    busy = true;
    tgWarn = null;
    try {
      const r = await api.tagsRent(t, days, gift);
      if (balance) balance = { ...balance, balance: r.user_balance };
      haptic(r.tg_applied ? 'success' : 'error');
      if (r.tg_applied) {
        const who = r.gift ? `подарен (tg_id ${r.recipient_tg_id})` : 'активен';
        showAlert(
          `Тег «${r.title}» ${who} до ${new Date(r.expires_at).toLocaleString('ru-RU')}`
        );
      } else {
        tgWarn = r.tg_error ?? 'Telegram не подтвердил установку тега.';
      }
      // оптимистично подтягиваем — refresh может опаздывать
      if (st && !r.gift) {
        st = {
          ...st,
          mine: { title: r.title, expires_at: r.expires_at, expired: false }
        };
      }
      title = '';
      giftOpen = false;
      giftTo = '';
      await refresh();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busy = false;
    }
  }

  async function cancel() {
    if (busy) return;
    if (!confirm('Снять свой тег? Деньги не возвращаются.')) return;
    busy = true;
    tgWarn = null;
    try {
      const r = await api.tagsCancel();
      haptic('light');
      if (!r.tg_applied) {
        tgWarn = r.tg_error ?? 'Telegram не подтвердил снятие тега.';
      }
      await refresh();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
    } finally {
      busy = false;
    }
  }

  async function reapply() {
    if (reapplyBusy) return;
    reapplyBusy = true;
    try {
      const r = await api.tagsReapply();
      if (r.tg_applied) {
        tgWarn = null;
        haptic('success');
        showAlert(`Тег «${r.title}» переустановлен.`);
        await refresh();
      } else {
        tgWarn = r.tg_error ?? 'Снова не удалось.';
        haptic('error');
      }
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
    } finally {
      reapplyBusy = false;
    }
  }
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Теги</h1>

{#if balance}
  <div class="bal muted">
    Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong>
  </div>
{/if}
<p class="muted small sub">
  Аренда подписи рядом с твоим ником в чате (реальный Telegram-титул, до 16 символов).
</p>

{#if tgWarn}
  <div class="card warn">
    <div class="warn-head">⚠️ Тег не установлен в Telegram</div>
    <div class="warn-msg">{tgWarn}</div>
    <button class="retry" disabled={reapplyBusy} on:click={reapply}>
      {reapplyBusy ? '…' : 'Попробовать ещё раз'}
    </button>
  </div>
{/if}

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="danger">{err}</div>
{:else if st}
  {#if st.mine}
    <div class="card mine">
      <div>
        Твой тег: <strong>«{st.mine.title}»</strong>
        {#if st.mine.expired}
          <span class="danger">истёк</span>
        {:else}
          <span class="muted small">до {new Date(st.mine.expires_at).toLocaleString('ru-RU')}</span>
        {/if}
      </div>
      <button class="cancel" disabled={busy} on:click={cancel}>Снять</button>
    </div>

    {#if expSoon}
      <div class="card ext" class:warn={st.mine.expired}>
        <div class="ext-head">
          {#if st.mine.expired}
            ⌛ Аренда истекла — продли, чтобы тег вернулся:
          {:else}
            ⏰ Тег истекает через ~{hoursLeft}ч — продлить?
          {/if}
        </div>
        <div class="ext-btns">
          {#each st.allowed_days as d}
            <button
              class="ext-btn"
              disabled={extendBusy || busy}
              on:click={() => extend(d)}
            >
              +{d} дн<span class="ext-c">{fmtCoins(st.per_day * d)}</span>
            </button>
          {/each}
        </div>
      </div>
    {/if}
  {/if}

  <section class="card">
    <div class="t">{st.mine ? 'Сменить / продлить тег' : 'Арендовать тег'}</div>
    <input
      class="inp"
      maxlength={st.max_len}
      placeholder="текст тега (до {st.max_len})"
      bind:value={title}
    />
    {#if titleTaken}
      <div class="danger small" style="margin:-4px 0 8px">Этот тег уже занят другим игроком</div>
    {/if}
    <div class="days">
      {#each st.allowed_days as d}
        <button class="day" class:active={days === d} on:click={() => (days = d)}>
          {d} дн
        </button>
      {/each}
    </div>
    <div class="muted small" style="margin:8px 0 10px">
      Цена: <strong style="color:var(--text)">{fmtCoins(price)}</strong>
      ({fmtCoins(st.per_day)}/день · уходит в банк чата)
    </div>

    <div class="gift">
      <label class="gift-toggle">
        <input type="checkbox" bind:checked={giftOpen} />
        <span>🎁 Подарить другому игроку</span>
      </label>
      {#if giftOpen}
        <div class="gift-body">
          <UserPicker bind:value={giftTo} placeholder="@username или tg_id получателя" />
          <div class="muted small" style="margin-top:6px">
            Деньги списываются с тебя, тег ставится получателю.
          </div>
        </div>
      {/if}
    </div>

    <button class="go" disabled={busy || !title.trim() || titleTaken || (giftOpen && !giftTo.trim())} on:click={rent}>
      {busy ? '…' : `${giftOpen ? 'Подарить' : 'Арендовать'} · ${fmtCoins(price)}`}
    </button>
  </section>

  {#if st.occupied.length}
    <div class="sec-title">Занятые теги</div>
    <div class="card occ">
      {#each st.occupied as o}
        <span class="chip">«{o}»</span>
      {/each}
    </div>
  {/if}
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .bal { font-size: 13px; }
  .sub { margin: 4px 0 14px; line-height: 1.45; }
  .small { font-size: 12px; }
  .t { font-weight: 700; font-size: 15px; margin-bottom: 10px; }
  .card { margin-bottom: 12px; }
  .mine {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
  }
  .cancel {
    padding: 8px 14px;
    border: 0;
    border-radius: 8px;
    background: var(--bg-elev-2);
    color: var(--text);
    font-weight: 600;
    font-size: 13px;
    cursor: pointer;
  }
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
  .days { display: flex; gap: 6px; }
  .day {
    flex: 1;
    padding: 9px;
    border: 1px solid var(--separator);
    background: var(--bg);
    color: var(--text);
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .day.active { border-color: var(--accent); background: var(--accent-soft); }
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
  .go:disabled { opacity: 0.5; }
  .sec-title {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin: 16px 0 8px;
  }
  .occ { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip {
    padding: 5px 10px;
    background: var(--bg-elev-2);
    border-radius: 999px;
    font-size: 12px;
  }
  .warn {
    border: 1px solid #c87a2a;
    background: rgba(200, 122, 42, 0.08);
  }
  .warn-head { font-weight: 700; font-size: 14px; margin-bottom: 6px; }
  .warn-msg { font-size: 13px; line-height: 1.45; margin-bottom: 10px; }
  .retry {
    padding: 8px 14px;
    border: 0;
    border-radius: 8px;
    background: var(--accent);
    color: var(--accent-text);
    font-weight: 600;
    font-size: 13px;
    cursor: pointer;
  }
  .ext {
    border: 1px solid var(--accent);
    background: var(--accent-soft);
  }
  .ext.warn {
    border-color: #c87a2a;
    background: rgba(200, 122, 42, 0.1);
  }
  .ext-head { font-weight: 700; font-size: 14px; margin-bottom: 10px; }
  .ext-btns { display: flex; gap: 6px; }
  .ext-btn {
    flex: 1;
    padding: 10px 8px;
    border: 0;
    border-radius: 9px;
    background: var(--accent);
    color: var(--accent-text);
    font-weight: 700;
    font-size: 13px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }
  .ext-btn:disabled { opacity: 0.55; }
  .ext-c { font-size: 11px; opacity: 0.85; font-weight: 600; }

  .gift { margin: 6px 0 12px; }
  .gift-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    cursor: pointer;
    user-select: none;
  }
  .gift-toggle input { margin: 0; }
  .gift-body { margin-top: 8px; }
</style>
