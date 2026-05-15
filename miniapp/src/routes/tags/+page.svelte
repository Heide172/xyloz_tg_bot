<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';
  import type { BalanceResponse } from '$lib/types';

  let balance: BalanceResponse | null = null;
  let st: any = null;
  let loading = true;
  let err: string | null = null;
  let busy = false;

  let title = '';
  let days = 1;

  $: search = typeof window !== 'undefined' ? window.location.search : '';
  $: price = st ? st.per_day * days : 0;
  $: titleTaken =
    st && title.trim() && st.occupied.includes(title.trim()) && st.mine?.title !== title.trim();

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
    busy = true;
    try {
      const r = await api.tagsRent(t, days);
      if (balance) balance = { ...balance, balance: r.user_balance };
      haptic('success');
      showAlert(`Тег «${r.title}» активен до ${new Date(r.expires_at).toLocaleString('ru-RU')}`);
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
    try {
      await api.tagsCancel();
      haptic('light');
      await refresh();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
    } finally {
      busy = false;
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
    <button class="go" disabled={busy || !title.trim() || titleTaken} on:click={rent}>
      {busy ? '…' : `Арендовать · ${fmtCoins(price)}`}
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
</style>
