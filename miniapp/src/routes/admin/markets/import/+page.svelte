<script lang="ts">
  import { api } from '$lib/api';
  import { haptic, showAlert } from '$lib/tg';

  let url = '';
  let busy = false;
  let res: { market_id: number; already_imported?: boolean; question?: string } | null = null;

  async function submit() {
    if (busy) return;
    if (!url.trim()) {
      showAlert('Введи URL');
      return;
    }
    busy = true;
    try {
      res = await api.adminMarketImport(url.trim());
      haptic('success');
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busy = false;
    }
  }

  $: search = typeof window !== 'undefined' ? window.location.search : '';
</script>

<a class="back" href={`/admin${search}`}>← к админке</a>
<h1 class="h1">Импорт рынка</h1>

<section class="card">
  <label class="lbl">
    <span class="muted small">URL (polymarket.com или manifold.markets)</span>
    <input
      type="text"
      placeholder="https://polymarket.com/market/..."
      bind:value={url}
    />
    <div class="muted small">
      Polymarket: только конкретные <strong>/market/&lt;slug&gt;</strong> или
      <strong>/event/&lt;event&gt;/&lt;market&gt;</strong> URL (event-категории не поддерживаются).
    </div>
  </label>

  <button class="play" disabled={busy} on:click={submit}>
    {busy ? 'Импортирую…' : 'Импортировать (комиссия 50)'}
  </button>

  {#if res}
    <div class="result success">
      {#if res.already_imported}
        Уже был импортирован: #<strong>{res.market_id}</strong>
      {:else}
        Импортирован #<strong>{res.market_id}</strong>:
        <span class="muted">{res.question ?? ''}</span>
      {/if}
      <a href={`/markets/${res.market_id}${search}`}>→ карточка</a>
    </div>
  {/if}
</section>

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .small { font-size: 12px; }
  .lbl { display: block; margin-bottom: 14px; }
  .lbl span { display: block; margin-bottom: 6px; }
  .lbl input {
    width: 100%; padding: 11px 12px; border: 1px solid var(--separator);
    border-radius: 9px; font-size: 16px; background: var(--bg); color: var(--text);
  }
  .play {
    width: 100%; padding: 14px; background: var(--accent); color: var(--accent-text);
    border: 0; border-radius: 10px; font-weight: 700; font-size: 15px; cursor: pointer;
  }
  .play:disabled { opacity: 0.6; }
  .result {
    margin-top: 14px; padding: 12px; border-radius: 10px; font-size: 14px;
  }
  .result.success { background: var(--positive-soft); color: var(--positive); }
</style>
