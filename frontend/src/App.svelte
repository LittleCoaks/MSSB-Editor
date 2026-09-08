<script lang="ts">
  import { onMount } from 'svelte'
  import { app, type Page } from './lib/state.svelte'
  import GameSetup from './lib/GameSetup.svelte'
  import Music from './lib/Music.svelte'
  import Files from './lib/Files.svelte'
  import Characters from './lib/Characters.svelte'
  import Stadiums from './lib/Stadiums.svelte'

  const pages: { id: Page; label: string }[] = [
    { id: 'files', label: 'Browse assets' }, { id: 'characters', label: 'Characters' }, { id: 'stadiums', label: 'Stadiums' }, { id: 'music', label: 'Music' }, { id: 'game', label: 'Game' },
  ]

  onMount(() => {
    const h = location.hash.replace('#', '')
    if (h.startsWith('entry/')) { app.selected = +h.slice(6); app.page = 'files' }
    else if (h.startsWith('characters/')) app.page = 'characters'
    else if (h.startsWith('stadiums/')) app.page = 'stadiums'
    else if (pages.some(p => p.id === h)) app.page = h as Page
    app.refresh()
    app.checkUpdates()
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
        {app.game.version ?? '?'} · {app.game.layout === 'iso' ? 'ISO' : 'Extracted folder'} · {app.game.writable ? 'editable' : 'view only'}
      </span>
      {#if !app.game.indexed}
        <button class="pill bad" onclick={() => app.go('game')} title="this version has not been indexed yet">not indexed</button>
      {/if}
    {:else}
      <span class="pill bad">no game selected</span>
    {/if}
  </div>
</header>

{#if app.update?.status?.available && !app.updateDismissed}
  <div class="update">
    <span>MSSB Editor {app.update.status.latest} is available (you have {app.update.version}).</span>
    <button class="primary" onclick={() => app.go('game')}>See what's new</button>
    <button onclick={() => (app.updateDismissed = true)} title="hide until the next start">Later</button>
  </div>
{/if}

<main>
  {#if app.error}
    <div class="card warn" style="margin:16px">Could not reach the editor: {app.error}</div>
  {:else if app.page === 'game'}
    <GameSetup />
  {:else if app.page === 'files'}
    <Files />
  {:else if app.page === 'characters'}
    <Characters />
  {:else if app.page === 'stadiums'}
    <Stadiums />
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
  .update { display: flex; gap: 10px; align-items: center; padding: 6px 16px; background: #1f2e22; border-bottom: 1px solid #3a5a48; font-size: 13px; }
</style>
