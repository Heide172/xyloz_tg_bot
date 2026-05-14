<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { tgReady, getTg } from '$lib/tg';

  let chatBound = true;

  onMount(() => {
    tgReady();
    const params = new URLSearchParams(window.location.search);
    const tg = getTg();
    const startParam = tg?.initDataUnsafe?.start_param;
    chatBound = params.has('chat_id') || !!startParam;

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
</style>
