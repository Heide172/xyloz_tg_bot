<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { tgReady, getTg } from '$lib/tg';

  let isTma = false;
  let chatBound = true;

  onMount(() => {
    tgReady();
    isTma = !!getTg();
    const params = new URLSearchParams(window.location.search);
    chatBound = params.has('chat_id');
    // BackButton — глобально
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
    :global(:root) {
      --bg: var(--tg-theme-bg-color, #ffffff);
      --text: var(--tg-theme-text-color, #000000);
      --hint: var(--tg-theme-hint-color, #999999);
      --link: var(--tg-theme-link-color, #2481cc);
      --button: var(--tg-theme-button-color, #2481cc);
      --button-text: var(--tg-theme-button-text-color, #ffffff);
      --section-bg: var(--tg-theme-section-bg-color, #f4f4f5);
      --section-header: var(--tg-theme-section-header-text-color, #6d6d72);
      --separator: var(--tg-theme-section-separator-color, #d1d1d6);
      --destructive: var(--tg-theme-destructive-text-color, #cc2929);
    }
    :global(body) {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.45 -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    :global(a) {
      color: var(--link);
      text-decoration: none;
    }
    :global(*, *::before, *::after) {
      box-sizing: border-box;
    }
  </style>
</svelte:head>

<main class="app">
  {#if !chatBound}
    <div class="warn">
      <p>chat_id не передан. Открой Mini App из чата через команду <code>/casino</code>.</p>
    </div>
  {/if}
  <slot />
</main>

<style>
  .app {
    padding: 12px 16px 24px;
    max-width: 720px;
    margin: 0 auto;
  }
  .warn {
    background: var(--section-bg);
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 12px;
    color: var(--hint);
    font-size: 13px;
  }
  code {
    background: rgba(0, 0, 0, 0.06);
    padding: 1px 5px;
    border-radius: 4px;
  }
</style>
