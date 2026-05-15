<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';
  import type { BalanceResponse } from '$lib/types';

  let balance: BalanceResponse | null = null;
  let col: any = null;
  let loading = true;
  let err: string | null = null;
  let busy = false;
  let tab: 'roll' | 'collection' = 'roll';
  let reveal: any[] = []; // выпавшие карточки для анимации
  let revealing = false;

  const RAR_LABEL: Record<string, string> = { R: 'R', SR: 'SR', SSR: 'SSR', UR: 'UR' };

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  async function refresh() {
    try {
      [balance, col] = await Promise.all([api.balance(), api.gachaCollection()]);
    } catch (e: any) {
      err = e?.message;
    } finally {
      loading = false;
    }
  }
  onMount(refresh);

  function charById(id: string) {
    return col?.items?.find((i: any) => i.char_id === id);
  }

  // Пока нет SR/SSR/UR-артов — фолбэк на существующий ассет.
  const FALLBACK = '/farm/heroine_idle.png';
  function imgErr(e: Event) {
    const el = e.target as HTMLImageElement;
    if (el && el.src.indexOf(FALLBACK) === -1) el.src = FALLBACK;
  }

  async function roll(count: number) {
    if (busy) return;
    busy = true;
    reveal = [];
    try {
      const r = await api.gachaRoll(count);
      if (balance) balance = { ...balance, balance: r.user_balance };
      revealing = true;
      // последовательное вскрытие
      for (const item of r.results) {
        reveal = [...reveal, item];
        haptic(item.rarity === 'UR' || item.rarity === 'SSR' ? 'success' : 'light');
        await new Promise((res) => setTimeout(res, count === 1 ? 0 : 180));
      }
      revealing = false;
      await refresh();
      if (r.refunded > 0) showAlert(`Дубли 5★ → возврат ${fmtCoins(r.refunded)}`);
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busy = false;
    }
  }

  async function setHeroine(id: string) {
    if (busy) return;
    busy = true;
    try {
      await api.gachaSetHeroine(id);
      haptic('success');
      await refresh();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
    } finally {
      busy = false;
    }
  }

  $: bannerChar = col ? charById(col.banner) : null;
</script>

<a class="back" href={`/farm${search}`}>← к ферме</a>
<h1 class="h1">Гача</h1>

{#if balance}
  <div class="bal muted">
    Баланс: <strong style="color: var(--text)">{fmtCoins(balance.balance)}</strong>
  </div>
{/if}

<div class="tabs">
  <button class="tb" class:active={tab === 'roll'} on:click={() => (tab = 'roll')}>Крутка</button>
  <button class="tb" class:active={tab === 'collection'} on:click={() => (tab = 'collection')}>
    Коллекция
  </button>
</div>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="danger">{err}</div>
{:else if col}
  {#if tab === 'roll'}
    {#if bannerChar}
      <div class="banner rar-UR">
        <div class="b-tag">★ RATE-UP ★</div>
        <img src={bannerChar.asset} alt={bannerChar.name} class="b-art" on:error={imgErr} />
        <div class="b-name">{bannerChar.name} <span class="rb">UR</span></div>
        <div class="muted small">Повышенный шанс в крутке</div>
      </div>
    {/if}

    <div class="pity">
      <div class="p-row">
        <span class="muted small">SSR гарант</span>
        <div class="bar"><div class="fill ssr" style="width:{(col.pity_ssr / col.ssr_pity) * 100}%"></div></div>
        <span class="small">{col.pity_ssr}/{col.ssr_pity}</span>
      </div>
      <div class="p-row">
        <span class="muted small">UR гарант</span>
        <div class="bar"><div class="fill ur" style="width:{(col.pity_ur / col.ur_pity) * 100}%"></div></div>
        <span class="small">{col.pity_ur}/{col.ur_pity}</span>
      </div>
    </div>

    {#if reveal.length}
      <div class="reveal" class:multi={reveal.length > 1}>
        {#each reveal as c (c.char_id + Math.random())}
          <div class="rc rar-{c.rarity}">
            <img src={c.asset} alt={c.name} on:error={imgErr} />
            <div class="rc-rar">{c.rarity}</div>
            <div class="rc-name">{c.name}</div>
            <div class="rc-meta small">
              {#if c.new}NEW{:else if c.refund > 0}дубль 5★ +{c.refund}{:else}+1★ → {c.stars}★{/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}

    <div class="roll-btns">
      <button class="rb1" disabled={busy} on:click={() => roll(1)}>
        Крутить ×1<span class="c">{fmtCoins(col.roll_cost)}</span>
      </button>
      <button class="rb10" disabled={busy} on:click={() => roll(10)}>
        Крутить ×10 (гарант SR+)<span class="c">{fmtCoins(col.x10_cost)}</span>
      </button>
    </div>
  {:else}
    <div class="grid">
      {#each col.items as it}
        <div
          class="cell rar-{it.rarity}"
          class:locked={!it.owned}
          class:active={col.active_heroine === it.char_id}
          on:click={() => it.owned && it.role === 'heroine' && setHeroine(it.char_id)}
          on:keydown={(e) =>
            e.key === 'Enter' &&
            it.owned &&
            it.role === 'heroine' &&
            setHeroine(it.char_id)}
          role="button"
          tabindex="0"
        >
          <img src={it.asset} alt={it.name} class:dim={!it.owned} on:error={imgErr} />
          <div class="c-rar">{it.rarity}</div>
          <div class="c-name">{it.name}</div>
          {#if it.owned}
            <div class="stars">{'★'.repeat(it.stars)}<span class="muted">{'☆'.repeat(5 - it.stars)}</span></div>
            {#if it.role === 'heroine'}
              <div class="hbtn" class:on={col.active_heroine === it.char_id}>
                {col.active_heroine === it.char_id ? 'активна' : 'выбрать'}
              </div>
            {:else}
              <div class="muted tiny">{it.base_value} cp/ур</div>
            {/if}
          {:else}
            <div class="muted tiny">не открыта</div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .bal { font-size: 13px; margin-bottom: 12px; }
  .small { font-size: 12px; }
  .tiny { font-size: 10px; }
  .tabs { display: flex; gap: 6px; background: var(--bg-elev); padding: 4px; border-radius: 11px; margin-bottom: 14px; }
  .tb { flex: 1; padding: 9px; border: 0; background: transparent; color: var(--text-muted); border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer; }
  .tb.active { background: var(--bg); color: var(--text); box-shadow: var(--shadow); }

  .banner {
    position: relative; border-radius: 16px; padding: 16px; text-align: center;
    margin-bottom: 14px; overflow: hidden;
    background: linear-gradient(135deg, #ffe7a8, #ffd1e8, #c8e4ff);
    box-shadow: 0 6px 20px rgba(0,0,0,0.2);
  }
  .b-tag { font-weight: 800; letter-spacing: 0.1em; color: #8a4b00; font-size: 12px; }
  .b-art { width: 150px; height: 150px; object-fit: cover; border-radius: 50%; margin: 8px auto; box-shadow: 0 4px 14px rgba(0,0,0,0.3); display: block; }
  .b-name { font-weight: 800; font-size: 17px; color: #1a1a1c; }
  .rb { background: linear-gradient(90deg,#ff8a00,#ff2d95); -webkit-background-clip: text; color: transparent; font-weight: 900; }

  .pity { background: var(--bg-elev); border-radius: 12px; padding: 10px 14px; margin-bottom: 14px; box-shadow: var(--shadow); }
  .p-row { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
  .p-row .muted { flex: 0 0 84px; }
  .bar { flex: 1; height: 7px; background: var(--bg-elev-2); border-radius: 4px; overflow: hidden; }
  .fill { height: 100%; }
  .fill.ssr { background: #b14cff; }
  .fill.ur { background: linear-gradient(90deg,#ff8a00,#ff2d95); }

  .roll-btns { display: flex; flex-direction: column; gap: 8px; }
  .rb1, .rb10 {
    display: flex; justify-content: space-between; align-items: center;
    padding: 14px 16px; border: 0; border-radius: 12px; font-weight: 700;
    font-size: 14px; cursor: pointer; color: var(--accent-text);
  }
  .rb1 { background: var(--accent); }
  .rb10 { background: linear-gradient(90deg,#7a4cff,#b14cff); }
  .rb1 .c, .rb10 .c { font-variant-numeric: tabular-nums; opacity: 0.92; }
  .rb1:disabled, .rb10:disabled { opacity: 0.55; }

  .reveal { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-bottom: 14px; }
  .reveal.multi .rc { width: calc(20% - 7px); }
  .rc {
    width: 130px; border-radius: 12px; padding: 8px; text-align: center;
    background: var(--bg-elev); animation: pop .35s ease-out;
  }
  @keyframes pop { from { transform: scale(.5); opacity: 0; } to { transform: scale(1); opacity: 1; } }
  .rc img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px; }
  .rc-rar { font-weight: 800; font-size: 12px; }
  .rc-name { font-size: 11px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rc-meta { color: var(--positive); }

  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .cell {
    background: var(--bg-elev); border-radius: 12px; padding: 8px; text-align: center;
    box-shadow: var(--shadow);
  }
  .cell.locked { opacity: 0.55; }
  .cell.active { outline: 2px solid var(--accent); }
  .cell img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px; }
  .cell img.dim { filter: grayscale(1) brightness(0.6); }
  .c-rar { font-weight: 800; font-size: 11px; margin-top: 4px; }
  .c-name { font-size: 11px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .stars { font-size: 12px; color: #f7d147; }
  .hbtn { font-size: 11px; font-weight: 700; color: var(--accent); margin-top: 2px; }
  .hbtn.on { color: var(--positive); }

  /* рамки по редкости */
  .rar-R { border: 2px solid #9aa0a6; }
  .rar-SR { border: 2px solid #4a90e2; }
  .rar-SSR { border: 2px solid #b14cff; box-shadow: 0 0 10px rgba(177,76,255,0.4); }
  .rar-UR { border: 2px solid #ffae00; box-shadow: 0 0 14px rgba(255,174,0,0.55); }
  .rar-R .c-rar, .rar-R .rc-rar { color: #9aa0a6; }
  .rar-SR .c-rar, .rar-SR .rc-rar { color: #4a90e2; }
  .rar-SSR .c-rar, .rar-SSR .rc-rar { color: #b14cff; }
  .rar-UR .c-rar, .rar-UR .rc-rar { color: #ffae00; }
</style>
