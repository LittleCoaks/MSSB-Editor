<script lang="ts">
  // The Audio page: the streamed music (listen, replace) and the sound effects, side by side as sub-tabs.
  import Music from './Music.svelte'
  import Sounds from './Sounds.svelte'

  let tab = $state<'music' | 'sounds'>(location.hash.startsWith('#music/sounds') ? 'sounds' : 'music')
  function go(t: 'music' | 'sounds') { tab = t; location.hash = t === 'sounds' ? 'music/sounds' : 'music' }
</script>

<div class="wrap">
  <nav class="tabs">
    <button class:on={tab === 'music'} onclick={() => go('music')}>Music</button>
    <button class:on={tab === 'sounds'} onclick={() => go('sounds')}>Sound effects</button>
  </nav>
  <div class="body">
    {#if tab === 'music'}<Music />{:else}<Sounds />{/if}
  </div>
</div>

<style>
  .wrap { flex: 1; display: flex; flex-direction: column; min-height: 0; }
  .tabs { display: flex; gap: 4px; padding: 0 20px; border-bottom: 1px solid var(--line); flex: none; }
  .tabs > button { background: none; border: none; border-bottom: 2px solid transparent; color: var(--dim); border-radius: 0; padding: 8px 12px; }
  .tabs > button.on { color: var(--fg); border-bottom-color: var(--acc); }
  .body { flex: 1; display: flex; min-height: 0; overflow: auto; }
</style>
