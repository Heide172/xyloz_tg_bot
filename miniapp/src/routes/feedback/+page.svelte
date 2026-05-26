<script lang="ts">
  import { onMount } from 'svelte';
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

  // tabs
  type Tab = 'chat' | 'mine';
  let tab: Tab = 'chat';
  type MyItem = {
    id: number;
    kind: 'bug' | 'idea';
    status: string;
    text: string;
    reward: number;
    default_reward: number;
    created_at: string | null;
    rewarded_at: string | null;
  };
  let myItems: MyItem[] = [];
  let myLoading = false;
  let myErr: string | null = null;
  let myLoaded = false;

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  async function loadMine() {
    if (myLoading) return;
    myLoading = true;
    myErr = null;
    try {
      const r = await api.feedbackMine();
      myItems = r.items;
      myLoaded = true;
    } catch (e: any) {
      myErr = e?.message ?? 'Не удалось загрузить';
    } finally {
      myLoading = false;
    }
  }

  function setTab(t: Tab) {
    tab = t;
    if (t === 'mine' && !myLoaded) loadMine();
  }

  function statusLabel(s: string): string {
    if (s === 'done') return 'закрыта';
    if (s === 'seen') return 'в работе';
    return 'в очереди';
  }

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
      if (r.registered) myLoaded = false; // протухает кэш «Моих»
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
      myLoaded = false;
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

<div class="tabs">
  <button class="tab" class:active={tab === 'chat'} on:click={() => setTab('chat')}>Новая</button>
  <button class="tab" class:active={tab === 'mine'} on:click={() => setTab('mine')}>Мои заявки</button>
</div>

{#if tab === 'chat'}
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
        <div class="ktabs">
          <button class="ktab" class:active={mkind === 'bug'} on:click={() => (mkind = 'bug')}>
            🐞 Баг
          </button>
          <button class="ktab" class:active={mkind === 'idea'} on:click={() => (mkind = 'idea')}>
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
{:else}
  {#if myLoading && !myLoaded}
    <div class="muted">Загрузка…</div>
  {:else if myErr}
    <div class="danger">{myErr}</div>
  {:else if myItems.length === 0}
    <div class="muted empty">
      У тебя пока нет заявок. Отправь баг или идею во вкладке «Новая».
    </div>
  {:else}
    <div class="list">
      {#each myItems as it}
        <div class="item" class:done={it.status === 'done'}>
          <div class="head">
            <span class="icon">{it.kind === 'bug' ? '🐞' : '💡'}</span>
            <span class="id">#{it.id}</span>
            <span class="status status-{it.status}">{statusLabel(it.status)}</span>
            {#if it.status === 'done' && it.reward > 0}
              <span class="reward">+{it.reward}г</span>
            {/if}
          </div>
          <div class="text">{it.text}</div>
          {#if it.created_at}
            <div class="muted small date">
              {new Date(it.created_at).toLocaleString('ru-RU')}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .tabs { display: flex; gap: 6px; margin: 8px 0 14px; }
  .tab {
    flex: 1; padding: 9px; border: 1px solid var(--separator);
    background: var(--bg); color: var(--text);
    border-radius: 8px; font-weight: 600; font-size: 13px; cursor: pointer;
  }
  .tab.active { border-color: var(--accent); background: var(--accent-soft); }
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
  .ktabs { display: flex; gap: 8px; margin-bottom: 10px; }
  .ktab {
    flex: 1; padding: 10px; border: 1px solid var(--separator); background: var(--bg);
    color: var(--text); border-radius: 10px; font-weight: 600; font-size: 14px; cursor: pointer;
  }
  .ktab.active { border-color: var(--accent); background: var(--accent-soft); }
  .done { text-align: center; line-height: 1.5; }

  .empty { padding: 20px 0; text-align: center; line-height: 1.5; }
  .list { display: flex; flex-direction: column; gap: 10px; }
  .item {
    padding: 12px;
    border: 1px solid var(--separator);
    border-radius: 10px;
    background: var(--bg);
  }
  .item.done { opacity: 0.7; }
  .head {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    margin-bottom: 6px; font-size: 13px;
  }
  .icon { font-size: 16px; }
  .id { font-weight: 700; }
  .status {
    padding: 2px 8px; border-radius: 999px; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .status-new { background: rgba(127,127,127,0.18); color: var(--text); }
  .status-seen { background: rgba(80,140,220,0.2); color: #4a8fe0; }
  .status-done { background: rgba(95,191,127,0.18); color: #5fbf7f; }
  .reward { font-weight: 700; color: #5fbf7f; font-size: 12px; }
  .text { font-size: 14px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
  .date { margin-top: 6px; }
  .small { font-size: 11px; }
</style>
