<script lang="ts">
  import { api } from '$lib/api';

  export let value = ''; // итоговая строка (@username или tg_id)
  export let placeholder = '@username или tg_id';
  export let disabled = false;

  type M = { tg_id: number; username: string | null; fullname: string | null };
  let items: M[] = [];
  let open = false;
  let loading = false;
  let timer: number | null = null;
  let activeIdx = -1;

  function label(m: M): string {
    if (m.username) return '@' + m.username;
    return m.fullname ?? String(m.tg_id);
  }

  async function search(q: string) {
    loading = true;
    try {
      const r = await api.members(q);
      items = r.items;
      open = items.length > 0;
      activeIdx = -1;
    } catch {
      items = [];
      open = false;
    } finally {
      loading = false;
    }
  }

  function onInput() {
    if (timer !== null) clearTimeout(timer);
    timer = window.setTimeout(() => search(value), 220);
  }

  function onFocus() {
    if (!disabled) search(value);
  }

  function choose(m: M) {
    value = label(m);
    open = false;
    items = [];
  }

  function onKey(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, items.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault();
      choose(items[activeIdx]);
    } else if (e.key === 'Escape') {
      open = false;
    }
  }
</script>

<div class="picker">
  <input
    type="text"
    {placeholder}
    {disabled}
    bind:value
    on:input={onInput}
    on:focus={onFocus}
    on:keydown={onKey}
    on:blur={() => setTimeout(() => (open = false), 150)}
    autocomplete="off"
  />
  {#if open}
    <ul class="dropdown">
      {#each items as m, i}
        <li>
          <button
            type="button"
            class:active={i === activeIdx}
            on:mousedown|preventDefault={() => choose(m)}
          >
            <span class="ph">{label(m)}</span>
            {#if m.username && m.fullname}
              <span class="sub muted">{m.fullname}</span>
            {/if}
          </button>
        </li>
      {/each}
      {#if loading}
        <li class="hint muted">поиск…</li>
      {/if}
    </ul>
  {/if}
</div>

<style>
  .picker {
    position: relative;
  }
  input {
    width: 100%;
    padding: 11px 12px;
    border: 1px solid var(--separator);
    border-radius: 9px;
    font-size: 16px;
    background: var(--bg);
    color: var(--text);
  }
  .dropdown {
    position: absolute;
    z-index: 20;
    left: 0;
    right: 0;
    margin: 4px 0 0;
    padding: 4px;
    list-style: none;
    background: var(--bg-elev);
    border: 1px solid var(--separator);
    border-radius: 10px;
    box-shadow: var(--shadow);
    max-height: 240px;
    overflow-y: auto;
  }
  .dropdown li button {
    display: flex;
    flex-direction: column;
    width: 100%;
    text-align: left;
    padding: 9px 10px;
    border: 0;
    background: transparent;
    color: var(--text);
    border-radius: 7px;
    cursor: pointer;
  }
  .dropdown li button.active,
  .dropdown li button:hover {
    background: var(--accent-soft);
  }
  .ph {
    font-weight: 600;
    font-size: 14px;
  }
  .sub {
    font-size: 11px;
  }
  .hint {
    padding: 8px 10px;
    font-size: 12px;
  }
</style>
