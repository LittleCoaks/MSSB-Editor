<script lang="ts">
  import { onMount } from 'svelte'
  import { app, type Page } from './lib/state.svelte'
  import GameSetup from './lib/GameSetup.svelte'
  import Browse from './lib/Browse.svelte'
  import Music from './lib/Music.svelte'

  const pages: { id: Page; label: string }[] = [
    { id: 'browse', label: 'Browse assets' }, { id: 'music', label: 'Music' }, { id: 'game', label: 'Game' },
  ]

  onMount(() => {
    const h = location.hash.replace('#', '')
    if (h.startsWith('entry/')) { app.selected = +h.slice(6); app.page = 'browse' }
    else if (pages.some(p => p.id === h)) app.page = h as Page
    app.refresh()
  })
</script>

<header>
  <div class="brand">MSSB Editor</div>
  <nav>
    {#each pages as p}
      <button class:on={app.page === p.id} onclick={() => app.go(p.id)}>{p.label}</button>
    {/each}
  </nav>
  <div class="status">
    {#if app.loading}
      <span class="dim">loading…</span>
    {:else if app.game?.ok}
      <span class="pill" class:rw={app.game.writable} title={app.game.setting ?? ''}>
        {app.game.layout === 'iso' ? 'ISO' : 'Extracted folder'} · {app.game.writable ? 'editable' : 'view only'}
      </span>
    {:else}
      <span class="pill bad">no game selected</span>
    {/if}
    <a href="/legacy" target="_blank" class="dim" title="The original technical view: raw entry table, hex viewer">Advanced view ↗</a>
  </div>
</header>

<main>
  {#if app.error}
    <div class="card warn" style="margin:16px">Could not reach the editor: {app.error}</div>
  {:else if app.page === 'game'}
    <GameSetup />
  {:else if app.page === 'browse'}
    <Browse />
  {:else if app.page === 'music'}
    <Music />
  {/if}
</main>

<style>
  header { display: flex; align-items: center; gap: 18px; padding: 8px 16px; background: var(--panel); border-bottom: 1px solid var(--line); flex: none; }
  .brand { font-weight: 700; font-size: 16px; white-space: nowrap; }
  nav { display: flex; gap: 4px; }
  nav button { background: none; border: 1px solid transparent; color: var(--dim); padding: 6px 12px; }
  nav button.on { color: var(--fg); background: var(--panel2); border-color: var(--line); }
  .status { margin-left: auto; display: flex; gap: 12px; align-items: center; white-space: nowrap; }
  .pill { border: 1px solid var(--line); border-radius: 12px; padding: 2px 10px; font-size: 12px; color: var(--dim); }
  .pill.rw { color: var(--acc2); border-color: #3a5a48; }
  .pill.bad { color: var(--warn); border-color: #6a3a3a; }
  main { flex: 1; min-height: 0; display: flex; flex-direction: column; }
</style>
