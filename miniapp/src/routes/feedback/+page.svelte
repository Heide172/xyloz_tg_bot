<script lang="ts">
  import { api } from '$lib/api';
  import { haptic, showAlert } from '$lib/tg';

  type Msg = { role: 'user' | 'bot'; text: string; ticket?: { id: number; kind: string } };

  let messages: Msg[] = [
    {
      role: 'bot',
      text:
        'Привет! Спроси что-нибудь про Бурмалду или опиши баг/идею — ' +
        'я отвечу и, если нужно, сам заведу заявку.'
    }
  ];
  let input = '';
  let busy = false;

  // фолбэк без ИИ
  let manual = false;
  let mkind: 'bug' | 'idea' = 'bug';
  let mtext = '';
  let msent = false;
  let mbusy = false;

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  async function send() {
    const t = input.trim();
    if (busy || t.length < 2) return;
    messages = [...messages, { role: 'user', text: t }];
    input = '';
    busy = true;
    try {
      const r = await api.feedbackAssist(t);
      messages = [
        ...messages,
        { role: 'bot', text: r.reply, ticket: r.registered ?? undefined }
      ];
      haptic(r.registered ? 'success' : 'light');
      if (r.degraded) manual = true;
    } catch (e: any) {
      messages = [
        ...messages,
        { role: 'bot', text: 'ИИ недоступен. Отправь заявку без ИИ ниже.' }
      ];
      manual = true;
      haptic('error');
    } finally {
      busy = false;
    }
  }

  async function sendManual() {
    if (mbusy) return;
    const t = mtext.trim();
    if (t.length < 5) {
      showAlert('Опиши подробнее (минимум 5 символов)');
      return;
    }
    mbusy = true;
    try {
      await api.feedback(mkind, t);
      msent = true;
      haptic('success');
    } catch (e: any) {
      showAlert(e?.message ?? 'Не удалось отправить');
      haptic('error');
    } finally {
      mbusy = false;
    }
  }
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Обратная связь</h1>

<section class="card chat">
  {#each messages as m}
    <div class="msg {m.role}">
      <div class="bubble">{m.text}</div>
      {#if m.ticket}
        <div class="ticket">
          ✅ Заявка #{m.ticket.id} ({m.ticket.kind === 'bug' ? 'баг' : 'идея'})
          зарегистрирована
        </div>
      {/if}
    </div>
  {/each}
  {#if busy}
    <div class="msg bot"><div class="bubble typing">…</div></div>
  {/if}

  <div class="composer">
    <textarea
      bind:value={input}
      rows="2"
      maxlength="2000"
      placeholder="Вопрос, баг или идея…"
      on:keydown={(e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send();
      }}
    ></textarea>
    <button class="send" disabled={busy || input.trim().length < 2} on:click={send}>
      {busy ? '…' : 'Отправить'}
    </button>
  </div>
  <button class="link" on:click={() => (manual = !manual)}>
    {manual ? 'Скрыть' : 'Отправить без ИИ'}
  </button>
</section>

{#if manual}
  {#if msent}
    <div class="card done">Спасибо! Заявка отправлена разработчику.</div>
  {:else}
    <section class="card">
      <div class="tabs">
        <button class="tab" class:active={mkind === 'bug'} on:click={() => (mkind = 'bug')}>
          🐞 Баг
        </button>
        <button class="tab" class:active={mkind === 'idea'} on:click={() => (mkind = 'idea')}>
          💡 Идея
        </button>
      </div>
      <textarea
        bind:value={mtext}
        rows="5"
        maxlength="2000"
        placeholder={mkind === 'bug' ? 'Что сломалось, как воспроизвести…' : 'Что добавить…'}
      ></textarea>
      <button class="send" disabled={mbusy || mtext.trim().length < 5} on:click={sendManual}>
        {mbusy ? 'Отправляю…' : 'Отправить заявку'}
      </button>
    </section>
  {/if}
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .chat { display: flex; flex-direction: column; gap: 10px; }
  .msg { display: flex; flex-direction: column; gap: 4px; max-width: 88%; }
  .msg.user { align-self: flex-end; align-items: flex-end; }
  .msg.bot { align-self: flex-start; }
  .bubble {
    padding: 9px 12px; border-radius: 12px; font-size: 14px; line-height: 1.45;
    white-space: pre-wrap; word-break: break-word;
  }
  .msg.user .bubble { background: var(--accent); color: var(--accent-text); }
  .msg.bot .bubble { background: var(--bg-elev-2, rgba(127,127,127,0.1)); color: var(--text); }
  .typing { letter-spacing: 2px; opacity: 0.6; }
  .ticket { font-size: 12px; color: #5fbf7f; }
  .composer { display: flex; gap: 8px; align-items: flex-end; margin-top: 4px; }
  textarea {
    width: 100%; padding: 10px 12px; border: 1px solid var(--separator);
    border-radius: 9px; font-size: 15px; background: var(--bg); color: var(--text);
    font-family: inherit; resize: vertical;
  }
  .send {
    padding: 12px 16px; background: var(--accent); color: var(--accent-text);
    border: 0; border-radius: 10px; font-weight: 700; font-size: 14px;
    cursor: pointer; white-space: nowrap;
  }
  .send:disabled { opacity: 0.5; }
  .link {
    background: none; border: 0; color: var(--text-muted); font-size: 13px;
    cursor: pointer; align-self: flex-start; padding: 4px 0; text-decoration: underline;
  }
  .tabs { display: flex; gap: 8px; margin-bottom: 10px; }
  .tab {
    flex: 1; padding: 10px; border: 1px solid var(--separator); background: var(--bg);
    color: var(--text); border-radius: 10px; font-weight: 600; font-size: 14px; cursor: pointer;
  }
  .tab.active { border-color: var(--accent); background: var(--accent-soft); }
  .done { text-align: center; line-height: 1.5; }
</style>
