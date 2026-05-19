<script lang="ts">
  import { api } from '$lib/api';
  import { haptic, showAlert } from '$lib/tg';

  let kind: 'bug' | 'idea' = 'bug';
  let text = '';
  let busy = false;
  let sent = false;

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  async function submit() {
    if (busy) return;
    const t = text.trim();
    if (t.length < 5) {
      showAlert('Опиши подробнее (минимум 5 символов)');
      return;
    }
    busy = true;
    try {
      await api.feedback(kind, t);
      sent = true;
      haptic('success');
    } catch (e: any) {
      showAlert(e?.message ?? 'Не удалось отправить');
      haptic('error');
    } finally {
      busy = false;
    }
  }
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Обратная связь</h1>

{#if sent}
  <div class="card done">
    Спасибо! {kind === 'bug' ? 'Баг' : 'Идея'} отправлен{kind === 'bug'
      ? ''
      : 'а'} разработчику.
    <button
      class="again"
      on:click={() => {
        sent = false;
        text = '';
      }}>Отправить ещё</button
    >
  </div>
{:else}
  <section class="card">
    <p class="muted small sub">
      Нашёл баг или есть идея по развитию? Опиши — придёт разработчику.
    </p>

    <div class="tabs">
      <button class="tab" class:active={kind === 'bug'} on:click={() => (kind = 'bug')}>
        🐞 Баг
      </button>
      <button class="tab" class:active={kind === 'idea'} on:click={() => (kind = 'idea')}>
        💡 Идея
      </button>
    </div>

    <textarea
      bind:value={text}
      rows="6"
      maxlength="2000"
      placeholder={kind === 'bug'
        ? 'Что сломалось, где, как воспроизвести…'
        : 'Что добавить или улучшить…'}
    ></textarea>
    <div class="cnt muted small">{text.length}/2000</div>

    <button class="send" disabled={busy || text.trim().length < 5} on:click={submit}>
      {busy ? 'Отправляю…' : 'Отправить'}
    </button>
  </section>
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .small { font-size: 12px; }
  .sub { margin: 0 0 14px; line-height: 1.45; }
  .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
  .tab {
    flex: 1;
    padding: 11px;
    border: 1px solid var(--separator);
    background: var(--bg);
    color: var(--text);
    border-radius: 10px;
    font-weight: 600;
    font-size: 14px;
    cursor: pointer;
  }
  .tab.active { border-color: var(--accent); background: var(--accent-soft); }
  textarea {
    width: 100%;
    padding: 11px 12px;
    border: 1px solid var(--separator);
    border-radius: 9px;
    font-size: 15px;
    background: var(--bg);
    color: var(--text);
    font-family: inherit;
    resize: vertical;
  }
  .cnt { text-align: right; margin: 4px 0 12px; }
  .send {
    width: 100%;
    padding: 14px;
    background: var(--accent);
    color: var(--accent-text);
    border: 0;
    border-radius: 10px;
    font-weight: 700;
    font-size: 15px;
    cursor: pointer;
  }
  .send:disabled { opacity: 0.5; }
  .done { text-align: center; line-height: 1.5; }
  .again {
    display: block;
    margin: 12px auto 0;
    padding: 9px 16px;
    background: var(--bg-elev-2);
    color: var(--text);
    border: 0;
    border-radius: 9px;
    font-weight: 600;
    cursor: pointer;
  }
</style>
