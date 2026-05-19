<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { tgReady, getTg, getStartRoute } from '$lib/tg';
  import { startBalanceSSE } from '$lib/sse';
  import { track } from '$lib/analytics';
  import { serviceState } from '$lib/service';

  let chatBound = true;

  onMount(() => {
    tgReady();
    const params = new URLSearchParams(window.location.search);
    const tg = getTg();
    const startParam = tg?.initDataUnsafe?.start_param;
    chatBound = params.has('chat_id') || !!startParam;

    startBalanceSSE();

    const unsubView = page.subscribe((p) => {
      if (p?.route?.id) track('view', { route: p.route.id });
    });

    // Deep-link в раздел: если в start_param указан роут — переходим туда.
    if ($page.route.id === '/') {
      const r = getStartRoute();
      if (r) goto(r + window.location.search);
    }

    // Принудительная схема: если Telegram говорит тёмная — добавляем класс
    // на html. Это страхует от случая, когда --tg-theme-text-color совпадает
    // с фоном (или вообще не задан).
    if (tg) {
      const scheme = tg.colorScheme;
      const root = document.documentElement;
      root.classList.remove('tg-dark', 'tg-light');
      if (scheme === 'dark') root.classList.add('tg-dark');
      else if (scheme === 'light') root.classList.add('tg-light');
    }

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

{#if $serviceState === 'updating'}
  <div class="updating-overlay">
    <div class="up-card">
      <div class="up-spin"></div>
      <div class="up-title">Обновляемся 🛠️</div>
      <div class="up-sub muted">
        Выкатываем свежую версию — это займёт минуту.<br />
        Страница оживёт автоматически, ничего не нажимай.
      </div>
    </div>
  </div>
{/if}

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
  .updating-overlay {
    position: fixed;
    inset: 0;
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    background: var(--bg, #0e0f12);
    backdrop-filter: blur(2px);
  }
  .up-card {
    text-align: center;
    max-width: 320px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
  }
  .up-spin {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    border: 3px solid rgba(127, 127, 127, 0.25);
    border-top-color: var(--accent, #4aa8ff);
    animation: up-rot 0.9s linear infinite;
  }
  @keyframes up-rot {
    to {
      transform: rotate(360deg);
    }
  }
  .up-title {
    font-size: 19px;
    font-weight: 700;
  }
  .up-sub {
    font-size: 13px;
    line-height: 1.5;
  }
</style>
