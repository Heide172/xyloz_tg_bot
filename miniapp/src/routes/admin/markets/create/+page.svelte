<script lang="ts">
  import { api } from '$lib/api';
  import { haptic, showAlert } from '$lib/tg';

  let question = '';
  let optsText = '';
  let duration = '7d';
  let busy = false;
  let createdId: number | null = null;

  async function submit() {
    if (busy) return;
    const options = optsText
      .split(/\n|,/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (options.length < 2) {
      showAlert('Нужно как минимум 2 варианта');
      return;
    }
    busy = true;
    try {
      const r = await api.adminMarketCreate({ question: question.trim(), options, duration });
      createdId = r.market_id;
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
<h1 class="h1">Создать рынок</h1>

<section class="card">
  <label class="lbl">
    <span class="muted small">Вопрос</span>
    <input type="text" placeholder="Кто выиграет финал?" bind:value={question} />
  </label>
  <label class="lbl">
    <span class="muted small">Варианты (по одному в строке или через запятую)</span>
    <textarea rows="5" placeholder="Команда А&#10;Команда Б&#10;Ничья" bind:value={optsText}></textarea>
  </label>
  <label class="lbl">
    <span class="muted small">Срок до закрытия (7d / 12h / 90m)</span>
    <input type="text" bind:value={duration} />
  </label>

  <button class="play" disabled={busy} on:click={submit}>
    {busy ? 'Создаю…' : 'Создать (комиссия 100)'}
  </button>

  {#if createdId !== null}
    <div class="result success">
      Создан рынок #<strong>{createdId}</strong>. Открой <a href={`/markets/${createdId}${search}`}>карточку</a>.
    </div>
  {/if}
</section>

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .small { font-size: 12px; }
  .lbl { display: block; margin-bottom: 14px; }
  .lbl span { display: block; margin-bottom: 6px; }
  .lbl input, .lbl textarea {
    width: 100%; padding: 11px 12px; border: 1px solid var(--separator);
    border-radius: 9px; font-size: 16px; background: var(--bg); color: var(--text);
    font-family: inherit;
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
