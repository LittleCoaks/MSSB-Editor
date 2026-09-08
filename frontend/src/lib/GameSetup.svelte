<script lang="ts">
  import { onMount } from 'svelte'
  import { app } from './state.svelte'
  import { api, native, kb, pollJob, type FsListing, type Job } from './api'

  // updates
  let updBusy = $state(false)
  let updMsg = $state('')
  let updJob = $state<Job | null>(null)
  async function checkNow() {
    updBusy = true; updMsg = ''
    try { await app.checkUpdates(true); const st = app.update?.status; if (st && !st.available && !st.error && st.latest) updMsg = 'You have the newest version.' }
    finally { updBusy = false }
  }
  async function setAuto(on: boolean) {
    try { const r = await api.updateSettings(on); if (app.update) app.update = { ...app.update, check_updates: r.check_updates } } catch (e: any) { updMsg = e.message }
  }
  async function install() {
    updBusy = true; updMsg = 'downloading…'
    try {
      const { job } = await api.installUpdate()
      const done = await pollJob(job, api.job, j => (updJob = j))
      updMsg = done.state === 'error' ? done.error ?? 'failed' : (done.result?.message ?? 'done')
    } catch (e: any) { updMsg = e.message } finally { updBusy = false }
  }
  const status = $derived(app.update?.status ?? null)

  let path = $state('')
  let msg = $state('')
  let busy = $state(false)
  let over = $state(false)
  let fs = $state<FsListing | null>(null)
  let dump = $state<Job | null>(null)
  let indexJob = $state<Job | null>(null)
  const g = $derived(app.game)

  async function buildIndex() {
    try {
      const { job } = await api.indexGame()
      indexJob = await pollJob(job, api.job, j => (indexJob = j))
      if (indexJob.state === 'done') await app.refresh()
    } catch (e: any) { msg = e.message }
  }

  async function use(p: string) {
    if (!p) return
    busy = true; msg = 'checking…'
    try {
      await api.setGame(p)
      msg = ''
      await app.refresh()
      if (app.game?.ok && app.game.indexed) app.go('files')
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
  <p class="dim">MSSB Editor works with your own copy of Mario Superstar Baseball — the American (GYQE01), European (GYQP01)
    or Japanese (GYQJ01) disc, or either kiosk demo. Give it the <b>disc image</b> (.iso / .gcm) or an <b>extracted game folder</b>.</p>

  <div class="card current">
    {#if g?.ok}
      <div><b>{g.version_name ?? 'Mario Superstar Baseball'}</b></div>
      <div class="dim">{g.setting}</div>
      <div class="dim">{g.layout === 'iso' ? 'Disc image' : 'Extracted folder'} · {g.entries} assets found</div>
      {#if !g.indexed}
        <div class="warn" style="margin-top:8px">
          This version has no asset index yet. Building one reads the whole of ZZZZ.dat once
          (several minutes); after that it is remembered.
        </div>
        <div class="row" style="margin-top:8px">
          <button class="primary" disabled={indexJob?.state === 'running'} onclick={buildIndex}>Build the asset index</button>
          {#if indexJob}
            {#if indexJob.state === 'running'}<span class="dim">{indexJob.note || 'working…'}</span>
            {:else if indexJob.state === 'error'}<span class="warn">{indexJob.error}</span>
            {:else}<span class="ok">Done — {indexJob.result?.entries} assets.</span>{/if}
          {/if}
        </div>
      {:else if g.index_stale}
        <div class="warn" style="margin-top:8px">
          The index does not match this copy of the game — it was built from a bigger ZZZZ.dat, or from a
          different version. Rebuild it to be sure of what is where.
          <button onclick={buildIndex}>Rebuild</button>
        </div>
      {:else if g.version && g.version !== 'GYQE01'}
        <div class="dim">Index built {g.index_built} · community asset names are only known for the American disc.</div>
      {/if}
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

  <div class="card" style="margin-top:16px">
    <h2 style="margin:0 0 6px">Updates</h2>
    <div class="row">
      <span>Version <b>{app.update?.version ?? '…'}</b></span>
      {#if status?.latest}<span class="dim">· newest release {status.latest}</span>{/if}
      <button onclick={checkNow} disabled={updBusy}>Check now</button>
      <label class="dim"><input type="checkbox" checked={app.update?.check_updates ?? true} onchange={e => setAuto((e.target as HTMLInputElement).checked)}> check on start-up</label>
      <a href={app.update?.releases ?? '#'} target="_blank" class="dim">all releases</a>
    </div>
    {#if status?.error}
      <p class="dim" style="margin:8px 0 0">Could not check: {status.error}</p>
    {:else if status && !status.latest}
      <p class="dim" style="margin:8px 0 0">No release has been published yet.</p>
    {:else if status?.available}
      <p class="ok" style="margin:8px 0 0">MSSB Editor {status.latest} is available.</p>
      {#if status.notes}<pre style="margin:8px 0;max-height:220px;white-space:pre-wrap">{status.notes}</pre>{/if}
      <div class="row">
        {#if status.asset && status.can_install}
          <button class="primary" onclick={install} disabled={updBusy}>Install {status.latest}</button>
          <span class="dim">downloads {status.asset.name} ({kb(status.asset.size)}) and starts it; the editor closes while the installer runs</span>
        {:else if status.asset}
          <a class="btn" href={status.asset.url}>Download {status.asset.name}</a>
          <span class="dim">a development checkout is not replaced by an installer</span>
        {:else}
          <a class="btn" href={status.url} target="_blank">Open the release page</a>
          <span class="dim">no installer for this platform is attached to the release</span>
        {/if}
      </div>
      {#if updJob && updJob.state === 'running'}<div class="bar" style="margin-top:8px"><i style="width:{Math.round(updJob.progress * 100)}%"></i></div>{/if}
    {/if}
    {#if updMsg}<p class="dim" style="margin:8px 0 0">{updMsg}</p>{/if}
  </div>
</div>

<style>
  .page { padding: 20px 24px; overflow: auto; }
  .current { margin: 14px 0; }
  .explorer { padding: 8px; }
  .explorer ul { list-style: none; margin: 6px 0 0; padding: 0; max-height: 300px; overflow: auto; }
  .explorer li { padding: 4px 8px; cursor: pointer; display: flex; justify-content: space-between; border-radius: 4px; }
  .explorer li:hover { background: var(--panel2); }
  .explorer li.iso { color: var(--acc2); }
</style>
