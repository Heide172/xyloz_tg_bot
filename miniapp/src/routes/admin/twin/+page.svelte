<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { haptic, showAlert } from '$lib/tg';
  import UserPicker from '$lib/UserPicker.svelte';

  let state: any = null;
  let logs: any[] = [];
  let loading = true;
  let err: string | null = null;
  let busy = false;
  let manualTarget = '';

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  function utcDate(s: string | null): string {
    if (!s) return '—';
    const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z');
    return d.toLocaleString('ru-RU');
  }

  async function refresh() {
    try {
      const r = await api.adminTwinStatus();
      state = r.state;
      logs = r.logs;
    } catch (e: any) {
      err = e?.message;
    } finally {
      loading = false;
    }
  }
  onMount(refresh);

  async function toggle() {
    if (busy || !state) return;
    busy = true;
    try {
      const r = await api.adminTwinToggle(!state.enabled);
      state = { ...state, enabled: r.enabled };
      haptic(r.enabled ? 'success' : 'light');
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
    } finally {
      busy = false;
    }
  }

  async function rotateNow() {
    if (busy) return;
    if (!confirm('Перезапустить ротацию прямо сейчас? Новый таргет.')) return;
    busy = true;
    try {
      const r = await api.adminTwinRotateNow();
      if (r.target) {
        haptic('success');
        showAlert(`Новый таргет: @${r.target.target_name}`);
      } else {
        showAlert('Нет валидных кандидатов в чате.');
      }
      await refresh();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
    } finally {
      busy = false;
    }
  }

  async function setManual() {
    if (busy || !manualTarget.trim()) return;
    busy = true;
    try {
      const r = await api.adminTwinSetTarget(manualTarget.trim());
      haptic('success');
      showAlert(`Таргет: @${r.target.target_name} (корпус ${r.target.persona_stats?.msg_count ?? '?'} сообщ.)`);
      manualTarget = '';
      await refresh();
    } catch (e: any) {
      showAlert(e?.message ?? 'Ошибка');
      haptic('error');
    } finally {
      busy = false;
    }
  }
</script>

<a class="back" href={`/admin${search}`}>← назад в админку</a>
<h1 class="h1">🎭 Двойник дня</h1>

{#if loading}
  <div class="muted">Загрузка…</div>
{:else if err}
  <div class="danger">{err}</div>
{:else if !state}
  <div class="card">
    Двойник в этом чате ещё не настраивался. Можно вручную запустить
    ротацию ниже.
    <button class="primary" disabled={busy} on:click={rotateNow}>
      Запустить ротацию сейчас
    </button>
  </div>
{:else}
  <section class="card status">
    <div class="row">
      <span class="muted">Активен:</span>
      <button
        class="toggle"
        class:on={state.enabled}
        disabled={busy}
        on:click={toggle}
      >
        {state.enabled ? 'Вкл' : 'Выкл'}
      </button>
    </div>
    <div class="row">
      <span class="muted">Сегодняшний таргет:</span>
      <strong>{state.target_name ? '@' + state.target_name : '—'}</strong>
    </div>
    <div class="row">
      <span class="muted">Ответов сегодня:</span>
      <strong>{state.replies_today}</strong>
    </div>
    <div class="row">
      <span class="muted">Последний ответ:</span>
      <strong>{utcDate(state.last_reply_at)}</strong>
    </div>
    {#if state.paused_until}
      <div class="row warn">
        <span class="muted">⏸ Пауза до:</span>
        <strong>{utcDate(state.paused_until)}</strong>
      </div>
    {/if}
    {#if state.persona_stats && Object.keys(state.persona_stats).length}
      <div class="persona">
        <div class="muted small">Профиль поведения:</div>
        <ul>
          <li>сообщений в корпусе: {state.persona_stats.msg_count}</li>
          <li>средняя длина: {state.persona_stats.avg_msg_len}</li>
          <li>reply-rate: {state.persona_stats.avg_reply_rate}</li>
          <li>response lag: {state.persona_stats.avg_response_lag}с</li>
          <li>
            активные часы MSK:
            {(state.persona_stats.active_hours_msk ?? []).join(', ') || '—'}
          </li>
        </ul>
      </div>
    {/if}
    <div class="actions">
      <button class="ghost" disabled={busy} on:click={rotateNow}>
        Перезапустить ротацию
      </button>
    </div>

    <div class="manual">
      <div class="muted small">Поставить вручную (минуя ротацию):</div>
      <div class="manual-row">
        <UserPicker
          bind:value={manualTarget}
          placeholder="@username или tg_id"
          disabled={busy}
        />
        <button class="primary" disabled={busy || !manualTarget.trim()} on:click={setManual}>
          Поставить
        </button>
      </div>
    </div>
  </section>

  <h2 class="h2">Лог последних ответов</h2>
  {#if logs.length === 0}
    <div class="muted empty">Пока пусто.</div>
  {:else}
    <div class="logs">
      {#each logs as l}
        <div class="log {l.status}">
          <div class="head">
            <span class="muted small">#{l.id}</span>
            <span class="status">{l.status}</span>
            {#if l.cost > 0}<span class="cost">−{l.cost}г</span>{/if}
            <span class="muted small">{utcDate(l.created_at)}</span>
          </div>
          <div class="text">{l.text}</div>
        </div>
      {/each}
    </div>
  {/if}
{/if}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .h2 { font-size: 17px; margin: 18px 0 10px; }
  .row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; font-size: 14px; }
  .row.warn { color: #c87a2a; }
  .toggle {
    padding: 6px 14px; border: 1px solid var(--separator); border-radius: 999px;
    background: var(--bg); color: var(--text-muted); font-weight: 700; cursor: pointer;
  }
  .toggle.on { background: var(--positive, #5fbf7f); color: white; border-color: transparent; }
  .toggle:disabled { opacity: 0.5; }
  .persona { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--separator); }
  .persona ul { margin: 4px 0 0; padding-left: 18px; font-size: 13px; }
  .persona li { margin: 2px 0; }
  .actions { margin-top: 12px; display: flex; gap: 8px; }
  .ghost {
    padding: 8px 14px; border: 1px solid var(--separator); border-radius: 8px;
    background: transparent; color: var(--text); font-weight: 600; font-size: 13px; cursor: pointer;
  }
  .primary {
    margin-top: 0; padding: 10px 16px; border: 0; border-radius: 9px;
    background: var(--accent); color: var(--accent-text); font-weight: 700; cursor: pointer;
    white-space: nowrap;
  }
  .primary:disabled { opacity: 0.5; }
  .manual {
    margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--separator);
    display: flex; flex-direction: column; gap: 8px;
  }
  .manual-row {
    display: grid; grid-template-columns: 1fr auto; gap: 8px;
  }
  .empty { padding: 16px; text-align: center; }
  .small { font-size: 11px; }
  .logs { display: flex; flex-direction: column; gap: 8px; }
  .log {
    padding: 10px 12px; border: 1px solid var(--separator); border-radius: 10px;
    background: var(--bg);
  }
  .log.err { border-color: rgba(220, 100, 100, 0.5); }
  .log.skipped { opacity: 0.6; }
  .head { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; font-size: 12px; }
  .head .status { font-weight: 700; text-transform: uppercase; }
  .log.sent .head .status { color: #5fbf7f; }
  .log.err .head .status { color: #d44; }
  .head .cost { color: #c87a2a; font-weight: 700; }
  .text { font-size: 13px; line-height: 1.45; white-space: pre-wrap; }
</style>
