<script lang="ts">
  // The seven stadiums: whole-scene view of each file variant, the props, textures and downloads.
  import { api, urls, kb, type StadiumEntry, type StadiumDetail, type PropModel } from './api'
  import { app } from './state.svelte'
  import ModelViewer, { type SceneProp } from './ModelViewer.svelte'

  let list = $state<StadiumEntry[]>([])
  let current = $state<number | null>(null)
  let d = $state<StadiumDetail | null>(null)
  let err = $state('')
  let loading = $state(false)
  let section = $state<'scene' | 'textures' | 'files'>('scene')
  let entry = $state<number | null>(null)     // the file shown in the viewer (a variant or a prop)
  let msg = $state('')
  let showProps = $state(true)   // draw the park's prop pack in the scene (waves, Chain Chomps, barrels...)
  let animateProps = $state(true)
  let propBank = $state('')

  async function load() {
    try { list = (await api.stadiums()).stadiums; err = '' } catch (e: any) { err = e.message }
    const h = location.hash.match(/^#stadiums\/(\d+)/)
    if (current === null) pick(h ? +h[1] : 0)
  }
  $effect(() => { app.game; load() })
  async function pick(id: number) {
    current = id; d = null; loading = true; entry = null
    location.hash = 'stadiums/' + id
    try { const x = await api.stadium(id); if (current === id) { d = x; entry = x.files[0]?.entry ?? null } }
    catch (e: any) { err = e.message } finally { loading = false }
  }
  const shownFile = $derived(d ? d.files.find(f => f.entry === entry) ?? null : null)
  const shownProp = $derived(d ? d.props.find(p => p.entry === entry) ?? null : null)
  const shown = $derived(shownFile ?? shownProp)
  // what the scene draws of the prop pack: models the pack places itself and the copies game.rel
  // stands around the park, in the day or night make that suits the shown file. Things that only
  // appear mid-game (rolling barrels, sandstorms, fireballs) have no resting place and stay out.
  // animations that happen once (a block or barrel breaking, a plant eating): not something to loop in the scene
  const ONE_SHOT = /clash|parts00_01|eat|nomikomi|throw|modori|open/
  const forSky = (m: PropModel) => !m.when || m.when === (shownFile?.sky?.night ? 'night' : 'day')
  const sceneProps = $derived<SceneProp[]>(!d || !shownFile || !showProps ? [] : d.props.flatMap(p =>
    p.models.filter(m => (m.fixed || m.instances.length) && forSky(m)).map(m => ({
      url: urls.glb(p.entry, m.section, m.banks.filter(b => !ONE_SHOT.test(b.name)).map(b => b.key).join(',') || undefined),
      instances: m.fixed ? null : m.instances }))))
  const unplaced = $derived(!d ? 0 : d.props.reduce((n, p) => n + p.models.filter(m => !m.fixed && !m.instances.length).length, 0))
  // day/night from the sky dome's texture; the same letter keeps files apart when two are alike
  const variantLabel = (f: { slots?: number[]; sky?: { night: boolean } | null }, i: number) => {
    if (!d) return ''
    const kind = f.sky ? (f.sky.night ? 'night' : 'day') : 'stadium'
    const twins = d.files.filter(x => (x.sky ? (x.sky.night ? 'night' : 'day') : 'stadium') === kind)
    return twins.length > 1 ? `${kind} ${String.fromCharCode(65 + twins.indexOf(f as any))}` : kind
  }
  async function exportDolphin() {
    if (!entry) return
    msg = 'exporting…'
    try { const r = await api.extract(entry, { dolphin: true }); msg = `saved ${r.written.length} texture(s) to ${r.dolphin_pack}; copy the GYQE01 folder into Dolphin's Load/Textures` } catch (e: any) { msg = e.message }
  }
  async function exportAll() {
    if (!entry) return
    msg = 'exporting…'
    try { const r = await api.extract(entry, { png: true, model: 'both' }); msg = `saved ${r.written.length} files to ${r.written[0].replace(/[\\/][^\\/]*$/, '')}` } catch (e: any) { msg = e.message }
  }
</script>

<div class="page">
  <aside>
    <ul>
      {#each list as s (s.id)}
        <li class:on={s.id === current}>
          <button onclick={() => pick(s.id)}>
            <span class="pic checker">{#if s.thumb !== null}<img loading="lazy" src={urls.thumb(s.thumb)} alt="" onerror={e => ((e.target as HTMLImageElement).style.visibility = 'hidden')}>{/if}</span>
            <span class="who"><span class="nm">{s.name}</span><span class="dim sub">{s.files.length} file{s.files.length === 1 ? '' : 's'}</span></span>
          </button>
        </li>
      {/each}
    </ul>
  </aside>

  <section class="main">
    {#if err}
      <div class="card warn" style="margin:16px">{err}</div>
    {:else if !d}
      <div class="dim" style="padding:20px">{loading ? 'loading…' : 'pick a stadium'}</div>
    {:else}
      <header>
        <div>
          <h1>{d.name}</h1>
          <div class="dim">stadium {d.id + 1} of 7 · {d.files.length} file{d.files.length === 1 ? '' : 's'}{#if d.props.length} · {d.props.length} props{/if}</div>
        </div>
        <div class="row">
          <button onclick={exportAll} disabled={!entry} title="Writes the shown file's models (glTF and OBJ) and its textures as PNG into the extracted folder">Export this file</button>
          <button onclick={exportDolphin} disabled={!entry} title="Writes the shown file's textures with Dolphin's dump names into extracted/dolphin/GYQE01, a folder you can drop into Dolphin's Load/Textures">Dolphin texture pack</button>
          {#if msg}<span class="dim small">{msg}</span>{/if}
        </div>
      </header>

      <nav class="tabs">
        <button class:on={section === 'scene'} onclick={() => (section = 'scene')}>Scene</button>
        <button class:on={section === 'textures'} onclick={() => (section = 'textures')}>Textures {#if shown}<span class="dim">{shown.textures}</span>{/if}</button>
        <button class:on={section === 'files'} onclick={() => (section = 'files')}>Files <span class="dim">{d.files.length + d.props.length}</span></button>
      </nav>

      <div class="body">
        <div class="pick">
          <div class="group">
            <span class="lbl">File</span>
            {#each d.files as f, i}<button class="chip" class:on={entry === f.entry} onclick={() => (entry = f.entry)} title={`${(f.triangles ?? 0).toLocaleString()} triangles · ${f.textures} textures · ${kb(f.size)} · table slots ${(f.slots ?? []).join(', ')}`}>{#if f.sky}<i class="sky" style="background:rgb({f.sky.rgb.join(',')})"></i>{/if}{variantLabel(f, i)}</button>{/each}
          </div>
          {#if d.props.length}
            <div class="group">
              <span class="lbl">Props</span>
              <label title={`draw the park's props in the stadium scene: scenery where the pack places it, and the copies the game's placement tables stand around the park` + (unplaced ? `. ${unplaced} object(s) the game only moves from code have no resting place and are left out; pick the pack to see them` : '')}><input type="checkbox" bind:checked={showProps}> in scene</label>
              <label title="loop each prop's animation in the scene (palm trees, boats, bench plants, signs)"><input type="checkbox" bind:checked={animateProps} disabled={!showProps}> animated</label>
              {#each d.props as p}<button class="chip" class:on={entry === p.entry} onclick={() => (entry = p.entry)} title={`${p.triangles.toLocaleString()} triangles · ${p.textures} textures`}>{p.name}</button>{/each}
            </div>
          {/if}
        </div>
        {#if section === 'scene' && entry !== null && shown}
          {#key entry}
            {#if shownFile}
              <ModelViewer {entry} models={shown.models ?? []} whole={true} height="62vh" overlay={urls.collision(entry)} props={sceneProps} {animateProps} />
            {:else if shownProp}
              <!-- a prop pack holds many objects around one origin: one at a time, each with only its own animations -->
              <ModelViewer {entry} models={shownProp.models} banks={shownProp.banks} bind:bank={propBank} height="62vh" />
            {/if}
          {/key}
          <p class="dim small" style="margin:8px 0 0">
            {#if shownFile}Every model section of the file drawn together{#if shown.models}: {shown.models.map(m => `${m.meshes.join(', ')} (${m.triangles.toLocaleString()})`).join(' · ')}{/if}.
            {:else}The pack's objects one at a time; the animation list holds only the shown object's own.{/if}
          </p>
        {:else if section === 'textures' && entry !== null}
          {#await api.entry(entry)}
            <div class="dim">loading…</div>
          {:then e}
            <div class="texgrid">
              {#each e.textures as t}
                <a class="tex" href={urls.tex(entry, t.n)} target="_blank" title={`#${t.n} ${t.width}×${t.height} ${t.fmt}`}>
                  <div class="checker"><img loading="lazy" src={urls.tex(entry, t.n)} alt="" style="max-width:128px;max-height:128px"></div>
                  <span class="dim small">{t.width}×{t.height} {t.fmt}</span>
                </a>
              {/each}
            </div>
          {/await}
        {:else if section === 'files'}
          <table>
            <thead><tr><th>what</th><th>models</th><th>size</th><th></th></tr></thead>
            <tbody>
              {#each d.files as f, i}
                <tr><td>{variantLabel(f, i)} <span class="dim">(table slots {(f.slots ?? []).join(', ')})</span></td><td class="dim">{(f.triangles ?? 0).toLocaleString()} triangles · {f.textures} textures · {f.sections} sections</td><td class="dim">{kb(f.size)}</td>
                  <td><a href={urls.data(f.entry)}>download</a> · <a href="#entry/{f.entry}" onclick={() => app.open(f.entry)}>browse</a></td></tr>
              {/each}
              {#each d.props as p}
                <tr><td>prop: {p.name}</td><td class="dim">{p.triangles.toLocaleString()} triangles · {p.textures} textures</td><td></td>
                  <td><a href={urls.data(p.entry)}>download</a> · <a href="#entry/{p.entry}" onclick={() => app.open(p.entry)}>browse</a></td></tr>
              {/each}
            </tbody>
          </table>
          <p class="dim small" style="margin-top:10px">The game's stadium table has three slots per stadium; a stadium with fewer files uses one file for several slots.</p>
        {/if}
      </div>
    {/if}
  </section>
</div>

<style>
  .page { flex: 1; display: flex; min-height: 0; }
  aside { width: 230px; flex: none; overflow: auto; border-right: 1px solid var(--line); padding: 10px; background: var(--panel); }
  aside ul { list-style: none; margin: 0; padding: 0; }
  aside li button { width: 100%; display: flex; align-items: center; gap: 10px; background: none; border: none; padding: 6px; border-radius: 6px; text-align: left; color: var(--fg); }
  aside li button:hover { background: var(--panel2); }
  aside li.on button { background: var(--sel); }
  .pic { width: 56px; height: 36px; border-radius: 6px; overflow: hidden; flex: none; display: flex; align-items: center; justify-content: center; }
  .pic img { max-width: 100%; max-height: 100%; }
  .who { display: flex; flex-direction: column; line-height: 1.2; min-width: 0; }
  .nm { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sub { font-size: 11px; }
  .main { flex: 1; min-width: 0; overflow: auto; display: flex; flex-direction: column; }
  header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding: 16px 20px 8px; }
  h1 { margin: 0 0 2px; }
  .tabs { display: flex; gap: 4px; padding: 0 20px; border-bottom: 1px solid var(--line); }
  .tabs > button { background: none; border: none; border-bottom: 2px solid transparent; color: var(--dim); border-radius: 0; padding: 8px 12px; }
  .tabs > button.on { color: var(--fg); border-bottom-color: var(--acc); }
  .body { padding: 14px 20px; }
  .pick { display: flex; flex-wrap: wrap; gap: 6px 22px; margin-bottom: 10px; }
  .group { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .lbl { color: var(--dim); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; margin-right: 4px; }
  .chip { padding: 4px 10px; border-radius: 14px; font-size: 13px; }
  .chip.on { border-color: var(--acc); background: var(--sel); }
  .sky { display: inline-block; width: 10px; height: 10px; border-radius: 5px; margin-right: 6px; vertical-align: -1px; border: 1px solid rgba(255,255,255,.25); }
  .small { font-size: 12px; }
  .texgrid { display: flex; flex-wrap: wrap; gap: 8px; }
  .tex { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 6px; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
  .tex .checker { display: inline-block; }
  table { width: 100%; }
  td { padding: 4px 10px; }
</style>
