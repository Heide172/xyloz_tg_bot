<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { tgReady, getTg } from '$lib/tg';

  let chatBound = true;

  onMount(() => {
    tgReady();
    const params = new URLSearchParams(window.location.search);
    const startParam = (window as any).Telegram?.WebApp?.initDataUnsafe?.start_param;
    chatBound = params.has('chat_id') || !!startParam;

    const tg = getTg();
    if (tg?.BackButton) {
      const onBack = () => {
        if ($page.route.id === '/') tg.close();
        else history.back();
      };
      tg.BackButton.onClick(onBack);
      const unsubscribe = page.subscribe((p) => {
        if (p.route.id && p.route.id !== '/') tg.BackButton.show();
        else tg.BackButton.hide();
      });
      return () => {
        tg.BackButton.offClick(onBack);
        unsubscribe();
      };
    }
  });
</script>

<svelte:head>
  <style>
    /* Базовая палитра — надежный fallback. Перекрывается переменными Telegram если есть. */
    :global(:root) {
      --bg:           #ffffff;
      --bg-elev:      #f4f4f7;
      --bg-elev-2:    #ebebef;
      --text:         #1a1a1c;
      --text-muted:   #6d6d72;
      --separator:    #d1d1d6;
      --accent:       #2481cc;
      --accent-text:  #ffffff;
      --accent-soft:  rgba(36, 129, 204, 0.14);
      --positive:     #1e8a47;
      --positive-soft:rgba(30, 138, 71, 0.14);
      --destructive:  #cc2929;
      --warning:      #e08f2c;
      --shadow:       0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.05);
    }
    @media (prefers-color-scheme: dark) {
      :global(:root) {
        --bg:           #0f0f12;
        --bg-elev:      #1c1c1f;
        --bg-elev-2:    #2a2a2e;
        --text:         #f4f4f7;
        --text-muted:   #98989d;
        --separator:    #2c2c2e;
        --accent:       #4fa3e3;
        --accent-soft:  rgba(79, 163, 227, 0.18);
        --positive:     #34c759;
        --positive-soft:rgba(52, 199, 89, 0.18);
        --destructive:  #ff453a;
        --warning:      #ff9f0a;
        --shadow:       0 1px 2px rgba(0,0,0,0.3), 0 4px 14px rgba(0,0,0,0.4);
      }
    }
    /* Перекрытие фактическими переменными Telegram, если они валидны. */
    :global(:root) {
      --bg:          var(--tg-theme-bg-color, var(--bg));
      --bg-elev:     var(--tg-theme-secondary-bg-color, var(--bg-elev));
      --text:        var(--tg-theme-text-color, var(--text));
      --text-muted:  var(--tg-theme-hint-color, var(--text-muted));
      --separator:   var(--tg-theme-section-separator-color, var(--separator));
      --accent:      var(--tg-theme-button-color, var(--accent));
      --accent-text: var(--tg-theme-button-text-color, var(--accent-text));
    }
    :global(body) {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font:
        16px/1.5 -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter',
        'Segoe UI', Roboto, sans-serif;
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }
    :global(a) {
      color: var(--accent);
      text-decoration: none;
    }
    :global(*, *::before, *::after) {
      box-sizing: border-box;
    }
    :global(button) {
      font-family: inherit;
      font-size: inherit;
      color: inherit;
    }
    :global(input) {
      font-family: inherit;
      color: var(--text);
    }
    /* Утилитарные классы доступны во всех страницах */
    :global(.h1)      { font-size: 28px; font-weight: 700; letter-spacing: -0.01em; margin: 6px 0 16px; line-height: 1.1; }
    :global(.h2)      { font-size: 18px; font-weight: 600; margin: 0 0 8px; }
    :global(.muted)   { color: var(--text-muted); }
    :global(.danger)  { color: var(--destructive); }
    :global(.success) { color: var(--positive); }
    :global(.card)    {
      background: var(--bg-elev);
      border-radius: 14px;
      padding: 16px;
      box-shadow: var(--shadow);
    }
    :global(.badge) {
      display: inline-block;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      border-radius: 5px;
      background: var(--bg-elev-2);
      color: var(--text-muted);
    }
    :global(.badge-open)      { background: var(--accent-soft);   color: var(--accent); }
    :global(.badge-resolved)  { background: var(--positive-soft); color: var(--positive); }
    :global(.badge-closed),
    :global(.badge-cancelled) { background: var(--bg-elev-2);     color: var(--text-muted); }
  </style>
</svelte:head>

<main class="app">
  {#if !chatBound}
    <div class="warn card">
      <strong>chat_id не передан.</strong>
      <p class="muted" style="margin: 4px 0 0;">
        Открой Mini App из чата через команду <code>/casino</code>.
      </p>
    </div>
  {/if}
  <slot />
</main>

<style>
  .app {
    padding: 16px 16px 32px;
    max-width: 720px;
    margin: 0 auto;
  }
  .warn {
    margin-bottom: 14px;
  }
  code {
    background: var(--bg-elev-2);
    padding: 1px 6px;
    border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, monospace;
    font-size: 0.9em;
  }
</style>
