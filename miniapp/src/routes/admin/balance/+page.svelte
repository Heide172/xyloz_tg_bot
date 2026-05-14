<script lang="ts">
  import { api } from '$lib/api';
  import { fmtCoins } from '$lib/format';
  import { haptic, showAlert } from '$lib/tg';

  let target = '';
  let amount = 100;
  let note = '';
  let busy = false;
  let result: { user_id: number; username: string | null; new_balance: number } | null = null;

  async function submit() {
    if (busy) return;
    if (!target.trim()) {
      showAlert('Укажи @username или tg_id');
      return;
    }
    if (!amount) {
      showAlert('Сумма не должна быть нулевой');
      return;
    }
    busy = true;
    try {
      result = await api.adminBalanceAdjust(target.trim(), amount, note.trim() || null);
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
<h1 class="h1">Баланс юзера</h1>

<section class="card">
  <label class="lbl">
    <span class="muted small">Целевой пользователь</span>
    <input type="text" placeholder="@username или tg_id" bind:value={target} />
  </label>
  <label class="lbl">
    <span class="muted small">Сумма (±)</span>
    <input type="number" step="10" bind:value={amount} />
    <div class="muted small">Положительное — начислить, отрицательное — списать.</div>
  </label>
  <label class="lbl">
    <span class="muted small">Комментарий (опц.)</span>
    <input type="text" placeholder="за что" bind:value={note} />
  </label>

  <button class="play" disabled={busy} on:click={submit}>
    {busy ? 'Применяю…' : 'Применить'}
  </button>

  {#if result}
    <div class="result success">
      {result.username ?? `user #${result.user_id}`} — новый баланс: <strong>{fmtCoins(result.new_balance)}</strong>
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
