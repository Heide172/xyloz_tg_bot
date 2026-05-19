<script lang="ts">
  import { onMount } from 'svelte';
  import { CHANGELOG } from '$lib/changelog';

  $: search = typeof window !== 'undefined' ? window.location.search : '';

  onMount(() => {
    // отметить, что патч-ноут просмотрен (снимает бейдж «новое»)
    try {
      if (CHANGELOG[0]) localStorage.setItem('cl_seen', CHANGELOG[0].date);
    } catch {
      /* ignore */
    }
  });

  function fmt(d: string): string {
    const [y, m, day] = d.split('-');
    return `${day}.${m}.${y}`;
  }
</script>

<a class="back" href={`/${search}`}>← назад</a>
<h1 class="h1">Что нового</h1>

{#each CHANGELOG as e}
  <section class="card">
    <div class="head">
      <span class="ttl">{e.title}</span>
      <span class="muted small">{fmt(e.date)}</span>
    </div>
    <ul>
      {#each e.items as it}
        <li>{it}</li>
      {/each}
    </ul>
  </section>
{/each}

<style>
  .back { display: inline-block; margin-bottom: 8px; font-size: 14px; color: var(--text-muted); }
  .small { font-size: 12px; }
  .head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; margin-bottom: 8px; }
  .ttl { font-weight: 700; font-size: 15px; }
  ul { margin: 0; padding-left: 18px; }
  li { font-size: 14px; line-height: 1.5; margin-bottom: 6px; }
  li:last-child { margin-bottom: 0; }
</style>
