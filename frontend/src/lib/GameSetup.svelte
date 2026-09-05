<script lang="ts">
  import { onMount } from 'svelte'
  import { app } from './state.svelte'
  import { api, native, kb, pollJob, type FsListing, type Job } from './api'

  let path = $state('')
  let msg = $state('')
  let busy = $state(false)
  let over = $state(false)
  let fs = $state<FsListing | null>(null)
  let dump = $state<Job | null>(null)
  const g = $derived(app.game)

  async function use(p: string) {
    if (!p) return
    busy = true; msg = 'checking…'
    try {
      await api.setGame(p)
      msg = ''
      await app.refresh()
      if (app.game?.ok) app.go('home')
    } catch (e: any) { msg = e.message } finally { busy = false }
  }
  async function browse(p: string) {
    try { fs = await api.fs(p) } catch (e: any) { msg = e.message }
  }
  function join(dir: string, name: string) { return !dir ? name : (dir.endsWith('\\') || dir.endsWith('/') ? dir + name : dir + '/' + name) }
  async function pick(kind: 'iso' | 'folder') {
    const n = native()
    if (!n) { msg = 'File dialogs open only in the desktop window. In a browser tab, use the explorer below or type the path.'; return }
    const p = kind === 'iso' ? await n.pick_iso() : await n.pick_folder()
    if (p) use(p)
  }
  function drop(e: DragEvent) {
    e.preventDefault(); over = false
    const f: any = e.dataTransfer?.files[0]
    const p = f?.pywebviewFullPath || f?.path
    if (p) use(p)
    else msg = 'This browser does not reveal dropped file paths. Use the explorer below, or run the desktop window.'
  }
  async function extract(only: string) {
    try {
      const { job } = await api.dumpGame(only)
      dump = await pollJob(job, api.job, j => (dump = j))
      if (dump.state === 'done') await app.refresh()
    } catch (e: any) { msg = e.message }
  }
  onMount(() => {
    path = g?.setting ?? ''
    const start = g?.setting ? (g.layout === 'iso' ? g.setting.replace(/[\\/][^\\/]*$/, '') : g.setting) : ''
    browse(start)
  })
</script>

<div class="page">
  <h1>Your game</h1>
  <p class="dim">MSSB Editor works with your own copy of Mario Superstar Baseball (GYQE01). Give it either the <b>disc image</b> (.iso / .gcm) or an <b>extracted game folder</b>.</p>

  <div class="card current">
    {#if g?.ok}
      <div><b>{g.setting}</b></div>
      <div class="dim">{g.layout === 'iso' ? 'Disc image' : 'Extracted folder'} · {g.entries} assets found</div>
      {#if g.writable}
        <div class="ok">Editing enabled — changes go to {g.files_dir}</div>
        {#if !g.edit_ready && g.iso}
          <div class="row" style="margin-top:8px"><span class="dim">Music editing works now. Replacing textures/models/other files also needs ZZZZ.dat and aaaa.dat in the folder (~452 MB):</span>
            <button onclick={() => extract('ZZZZ.dat,aaaa.dat')}>Prepare for editing</button></div>
          {#if dump}
            <div class="row" style="margin-top:8px">
              {#if dump.state === 'running'}<span class="bar"><i style="width:{Math.round(dump.progress * 100)}%"></i></span> {Math.round(dump.progress * 100)}%
              {:else if dump.state === 'error'}<span class="warn">{dump.error}</span>
              {:else}<span class="ok">Done. File replacement is now enabled.</span>{/if}
            </div>
          {/if}
        {:else if g.edit_ready}
          <div class="ok">File replacement enabled (ZZZZ.dat, aaaa.dat and main.dol are in the folder).</div>
        {/if}
      {:else}
        <div class="warn">View only. To change music or assets, extract the image to a folder:</div>
        <div class="row" style="margin-top:8px">
          <button onclick={() => extract('snd/')}>Extract just what music editing needs (~180 MB)</button>
          <button onclick={() => extract('')}>Extract the whole game (1.4 GB)</button>
          <span class="dim">→ {g.default_dump}</span>
        </div>
        {#if dump}
          <div class="row" style="margin-top:8px">
            {#if dump.state === 'running'}<span class="bar"><i style="width:{Math.round(dump.progress * 100)}%"></i></span> {Math.round(dump.progress * 100)}%
            {:else if dump.state === 'error'}<span class="warn">{dump.error}</span>
            {:else}<span class="ok">Done. Editing is now enabled.</span>{/if}
          </div>
        {/if}
      {/if}
    {:else}
      <div class="warn">{g?.problem || g?.error || 'No game selected yet.'}</div>
    {/if}
  </div>

  <div class="drop" class:over ondragover={e => { e.preventDefault(); over = true }} ondragleave={() => (over = false)} ondrop={drop} role="region" aria-label="drop zone">
    <div style="font-size:26px">📀</div>
    Drop your ISO or game folder here
    <div class="dim" style="font-size:12px;margin-top:4px">or use the buttons below</div>
  </div>

  <div class="row" style="margin:12px 0">
    <button onclick={() => pick('iso')}>Browse for ISO…</button>
    <button onclick={() => pick('folder')}>Browse for folder…</button>
    <input type="text" bind:value={path} placeholder="…or paste a path" style="min-width:360px" onkeydown={e => e.key === 'Enter' && use(path)}>
    <button class="primary" disabled={busy} onclick={() => use(path)}>Use</button>
    {#if msg}<span class="warn">{msg}</span>{/if}
  </div>

  <div class="explorer card">
    <div class="row">
      <button onclick={() => browse(fs?.parent ?? '')} title="up">↑</button>
      <input type="text" value={fs?.path ?? ''} style="flex:1" onkeydown={e => e.key === 'Enter' && browse((e.target as HTMLInputElement).value)}>
      <button onclick={() => fs && use(fs.path)}>{fs?.layout ? `Use this folder (${fs.layout})` : 'Use this folder'}</button>
    </div>
    <ul>
      {#each fs?.dirs ?? [] as d}
        <li onclick={() => browse(join(fs!.path, d))}><span>📁 {d}</span></li>
      {/each}
      {#each fs?.files ?? [] as f}
        <li class="iso" onclick={() => use(join(fs!.path, f.name))}><span>💿 {f.name}</span><span class="dim">{kb(f.size)} · click to use</span></li>
      {/each}
    </ul>
  </div>
</div>

<style>
  .page { padding: 20px 24px; overflow: auto; max-width: 900px; }
  .current { margin: 14px 0; }
  .explorer { padding: 8px; }
  .explorer ul { list-style: none; margin: 6px 0 0; padding: 0; max-height: 300px; overflow: auto; }
  .explorer li { padding: 4px 8px; cursor: pointer; display: flex; justify-content: space-between; border-radius: 4px; }
  .explorer li:hover { background: var(--panel2); }
  .explorer li.iso { color: var(--acc2); }
</style>
