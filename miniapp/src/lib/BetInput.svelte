<script lang="ts">
  export let amount: number;
  export let balance: number | null = null;
  export let disabled = false;
  const presets = [10, 50, 100, 500, 1000];
</script>

<div class="row">
  <input
    type="number"
    bind:value={amount}
    min="10"
    step="10"
    inputmode="numeric"
    {disabled}
  />
  <div class="presets">
    {#each presets as p}
      <button class="preset" {disabled} on:click={() => (amount = p)}>{p}</button>
    {/each}
    {#if balance !== null}
      <button class="preset" {disabled} on:click={() => (amount = Math.max(10, balance))}
        >all</button
      >
    {/if}
  </div>
</div>

<style>
  .row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  input {
    flex: 0 0 110px;
    padding: 11px 12px;
    border: 1px solid var(--separator);
    border-radius: 9px;
    font-size: 16px;
    background: var(--bg);
  }
  .presets {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    flex: 1;
  }
  .preset {
    padding: 7px 10px;
    border: 0;
    background: var(--bg-elev-2);
    color: var(--text);
    border-radius: 8px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
  }
  .preset:disabled {
    opacity: 0.5;
    cursor: default;
  }
</style>
