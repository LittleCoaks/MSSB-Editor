<script lang="ts">
  import { app } from './state.svelte'
  import { kb } from './api'

  const cats = $derived(app.catalog?.categories ?? [])
  const g = $derived(app.game)
  const counts = $derived({
    textures: [...app.entries.values()].reduce((s, e) => s + e.ntex, 0),
    models: [...app.entries.values()].filter(e => e.kind === 'container').length,
    music: [...app.entries.values()].filter(e => e.archive === 'disc').length,
  })
</script>

<div class="home">
  <section class="card hero">
    {#if g?.ok}
      <h1>Your game is ready</h1>
      <p class="dim" title={g.setting ?? ''}>{g.setting}</p>
      {#if g.writable}
        <p><span class="ok">●</span> Editable: changes are written to <code>{g.files_dir}</code>. The original of anything you replace is backed up automatically.</p>
      {:else}
        <p><span class="warn">●</span> View only: this is a disc image, so nothing can be changed yet. <a href="#game" onclick={() => app.go('game')}>Extract it to a folder</a> to enable editing.</p>
      {/if}
    {:else}
      <h1>Welcome</h1>
      <p>Point the editor at your copy of Mario Superstar Baseball to get started.</p>
      <button class="primary" onclick={() => app.go('game')}>Choose your game</button>
    {/if}
  </section>

  {#if g?.ok}
    <section class="actions">
      <button class="card action" onclick={() => { app.category = 'characters'; app.go('browse') }}>
        <span class="icon">🎮</span><b>Browse assets</b>
        <span class="dim">Characters, stadiums, menus: {counts.textures.toLocaleString()} textures, {counts.models} asset packs with models</span>
      </button>
      <button class="card action" onclick={() => app.go('music')}>
        <span class="icon">🎵</span><b>Change the music</b>
        <span class="dim">Listen to the {counts.music} soundtrack streams and replace any of them with your own song</span>
      </button>
      <button class="card action" onclick={() => { app.category = 'movies'; app.go('browse') }}>
        <span class="icon">🎬</span><b>Movies &amp; sounds</b>
        <span class="dim">The intro movies and the voice / sound-effect bank</span>
      </button>
    </section>

    <section>
      <h3>What's inside</h3>
      <div class="cats">
        {#each cats as c}
          <button class="card cat" onclick={() => { app.category = c.id; app.group = ''; app.go('browse') }}>
            <b>{c.name}</b> <span class="dim">{c.count} items · {c.groups.length} groups</span>
          </button>
        {/each}
      </div>
    </section>
  {/if}
</div>

<style>
  .home { padding: 20px 24px; overflow: auto; max-width: 1100px; }
  .hero { padding: 22px 24px; margin-bottom: 18px; }
  .hero p { margin: 6px 0; }
  .actions { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-bottom: 22px; }
  .action { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; text-align: left; cursor: pointer; }
  .action:hover { border-color: var(--acc); }
  .action .icon { font-size: 26px; }
  .cats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
  .cat { text-align: left; display: flex; flex-direction: column; gap: 2px; padding: 10px 14px; cursor: pointer; }
</style>
