<script lang="ts">
  // The roster: the game's 32 characters, each with its models, colour
  // variants, equipment, animations, sounds and files.
  import { api, urls, kb, type RosterEntry, type RosterDetail, type SlotInfo } from './api'
  import { app } from './state.svelte'
  import ModelViewer from './ModelViewer.svelte'

  let roster = $state<RosterEntry[]>([])
  let current = $state<number | null>(null)
  let d = $state<RosterDetail | null>(null)
  let filter = $state('')
  let err = $state('')
  let section = $state<'model' | 'sounds' | 'files'>('model')
  let modelRole = $state('')       // which of the character's models is shown
  let variant = $state<number | null>(null)
  let bank = $state('')            // animation bank shown in the viewer
  let pose = $state<number | undefined>(undefined)   // hand pose for an equipment model (the bat pose)
  let loadingDetail = $state(false)

  async function load() {
    try { roster = (await api.roster()).characters; err = '' } catch (e: any) { err = e.message }
    const h = location.hash.match(/^#characters\/(\d+)/)
    if (current === null) pick(h ? +h[1] : roster[0]?.id ?? 0)
  }
  $effect(() => { app.game; load() })

  async function pick(id: number) {
    current = id; d = null; loadingDetail = true; variant = null; modelRole = ''; bank = ''; pose = undefined
    location.hash = 'characters/' + id
    try { const x = await api.character(id); if (current === id) { d = x; modelRole = x.models[0]?.role ?? ''; section = section === 'sounds' && !x.sounds ? 'model' : section } }
    catch (e: any) { err = e.message } finally { loadingDetail = false }
  }

  const shown = $derived(roster.filter(c => !filter || c.name.toLowerCase().includes(filter.toLowerCase()) || c.slots.some(s => s.name.toLowerCase().includes(filter.toLowerCase()))))
  const model = $derived(d?.models.find(m => m.role === modelRole) ?? d?.parts.find(m => m.role === modelRole) ?? d?.models[0] ?? null)
  const isBody = $derived(!!d && d.models.some(m => m.role === modelRole))
  // the viewer takes the entry's own bank list; the roster's banks carry friendlier labels
  const viewerBanks = $derived(d && isBody ? d.banks.map(b => ({ key: b.key, entry: b.entry, section: 0, label: b.label, sequences: b.playable })) : [])
  const viewerVariants = $derived(d && isBody ? d.variants.filter(v => v.texture_entry !== null).map(v => ({ slot: v.slot, name: v.name, entry: v.texture_entry! })) : [])
  const viewerParts = $derived(d && isBody ? d.viewer_parts.flatMap(p => [`L_${p}`, `R_${p}`]) : [])

  // sounds
  let player: HTMLAudioElement | undefined = $state()
  let playing = $state<number | null>(null)
  function play(n: number) {
    if (!d?.sounds) return
    playing = n
    queueMicrotask(() => { if (player) { player.src = urls.audio(d!.sounds!.entry, n); player.load(); player.play().catch(() => {}) } })
  }

  // export
  let exportMsg = $state('')
  let exporting = $state(false)
  async function exportAll(what: string) {
    if (!d) return
    exporting = true; exportMsg = 'exporting…'
    try { const r = await api.exportCharacter(d.id, what); exportMsg = `${r.written.length} files written to ${r.dest}\\${d.name}` }
    catch (e: any) { exportMsg = e.message } finally { exporting = false }
  }

  // slot cloning (kept from the old page, folded away)
  let showClone = $state(false)
  let slots = $state<SlotInfo[]>([])
  let editable = $state(false)
  let source = $state(2)
  let target = $state(1)
  let copy = $state(true)
  let busy = $state(false)
  let msg = $state('')
  let ok = $state(false)
  async function loadSlots() { try { const r = await api.characters(); slots = r.slots; editable = r.editable } catch (e: any) { msg = e.message } }
  $effect(() => { if (showClone) loadSlots() })
  async function clone() {
    busy = true; msg = 'cloning… (copying the character files takes a few seconds)'; ok = false
    try {
      const r = await api.cloneCharacter(source, target, copy)
      msg = `${r.target_name} now plays as ${r.source_name}: ${r.copied} files copied, ${r.shared} descriptors shared.`
      ok = true; await app.refresh(); await loadSlots()
    } catch (e: any) { msg = e.message } finally { busy = false }
  }
  async function restore(slot: number) {
    busy = true; msg = 'restoring…'; ok = false
    try { await api.restoreCharacter(slot); msg = `Slot ${slot} restored.`; ok = true; await app.refresh(); await loadSlots() } catch (e: any) { msg = e.message } finally { busy = false }
  }
  const cloned = $derived(slots.filter(s => s.clone_of !== null))
  const secs = (s: number) => s >= 1 ? s.toFixed(2) + ' s' : Math.round(s * 1000) + ' ms'
</script>

<div class="page">
  <aside>
    <input type="search" placeholder="Find a character…" bind:value={filter}>
    <ul>
      {#each shown as c (c.id)}
        <li class:on={c.id === current}>
          <button onclick={() => pick(c.id)}>
            <span class="face checker">{#if c.thumb !== null}<img loading="lazy" src={urls.thumb(c.thumb)} alt="" onerror={e => ((e.target as HTMLImageElement).style.visibility = 'hidden')}>{/if}</span>
            <span class="who"><span class="nm">{c.name}</span>{#if c.variants > 1}<span class="dim sub">{c.variants} colours</span>{/if}</span>
          </button>
        </li>
      {/each}
    </ul>
  </aside>

  <section class="main">
    {#if err}
      <div class="card warn" style="margin:16px">{err}</div>
    {:else if !d}
      <div class="dim" style="padding:20px">{loadingDetail ? 'loading…' : 'pick a character'}</div>
    {:else}
      <header>
        <div>
          <h1>{d.name}</h1>
          <div class="dim">character {d.id + 1} of 32 · roster slot {d.slot}{#if d.variants.length > 1} · {d.variants.length} colour variants{/if}</div>
        </div>
        <div class="row">
          <button onclick={() => exportAll('models,textures,sounds')} disabled={exporting} title="Writes the model (glb and dae with every animation, obj), textures, colour variants and voice clips into the extracted folder">Export everything</button>
          <button onclick={() => exportAll('dolphin')} disabled={exporting} title="Writes every texture of this character with Dolphin's dump names into extracted/dolphin/GYQE01, a folder you can drop into Dolphin's Load/Textures">Dolphin texture pack</button>
          {#if exportMsg}<span class="dim small">{exportMsg}</span>{/if}
        </div>
      </header>

      <nav class="tabs">
        <button class:on={section === 'model'} onclick={() => (section = 'model')}>Model & animations</button>
        {#if d.sounds}<button class:on={section === 'sounds'} onclick={() => (section = 'sounds')}>Sounds <span class="dim">{d.sounds.samples.length}</span></button>{/if}
        <button class:on={section === 'files'} onclick={() => (section = 'files')}>Files <span class="dim">{d.files.length}</span></button>
      </nav>

      <div class="body">
        {#if section === 'model'}
          <div class="pick">
            <div class="group">
              <span class="lbl">Model</span>
              {#each d.models as m}<button class="chip" class:on={modelRole === m.role} onclick={() => { modelRole = m.role; pose = undefined }} title={`${m.triangles.toLocaleString()} triangles · ${m.textures} textures`}>{m.role}</button>{/each}
            </div>
            {#if d.parts.length}
              <div class="group">
                <span class="lbl">Equipment</span>
                {#each d.parts as p}
                  <button class="chip" class:on={modelRole === p.role && pose === undefined} onclick={() => { modelRole = p.role; pose = undefined }} title={`${p.triangles.toLocaleString()} triangles${p.poses ? ` · ${p.poses} hand poses` : ''}`}>{p.role}</button>
                  {#if p.bat_pose !== null && p.bat_pose !== undefined}<button class="chip" class:on={modelRole === p.role && pose === p.bat_pose} onclick={() => { modelRole = p.role; pose = p.bat_pose! }} title="the hand's bat pose: the bat is modelled inside the hand and pulled out by this pose">{p.role} with bat</button>{/if}
                {/each}
              </div>
            {/if}
          </div>
          {#if model}
            {#key model.entry + ':' + model.section}
              <ModelViewer entry={model.entry} models={model.models} banks={viewerBanks} parts={viewerParts} variants={viewerVariants} bind:bank height="56vh" {pose} />
            {/key}
            <p class="dim small" style="margin:8px 0 0">
              {model.role}: {model.meshes.join(', ')} · {model.triangles.toLocaleString()} triangles · {model.textures} textures · {kb(model.size)}.
              {#if isBody}Pick an animation bank above to play its animations; the colour dropdown draws the model with a variant's texture set; hands, gloves and the bat attach to the wrists. The bat is not a separate model: it is built into the batting hands and pulled out by a hand pose.{/if}
            </p>
          {/if}
          {#if isBody && d.banks.length}
            <h3 style="margin-top:16px">Animation banks <span class="dim" style="font-weight:400;text-transform:none;letter-spacing:0">· click one to play its animations in the viewer</span></h3>
            <div class="banks">
              {#each d.banks as b}
                <div class="bank" class:on={bank === b.key}>
                  <button class="bankbtn" onclick={() => (bank = bank === b.key ? '' : b.key)}><b>{b.label}</b> <span class="dim">{b.playable} animations{#if b.playable < b.sequences.length} <span title="sequences that hold the rest pose for their whole length">(+{b.sequences.length - b.playable} empty)</span>{/if}</span></button>
                  {#if b.named}<div class="dim small seqs" title={b.sequences.join(', ')}>{b.sequences.join(' · ')}</div>{:else}<div class="dim small">names not recovered for this bank</div>{/if}
                  <a class="small" href={urls.data(b.entry)}>download bank</a>
                </div>
              {/each}
            </div>
          {/if}
        {:else if section === 'sounds' && d.sounds}
          <p class="dim" style="margin-top:0">The character's voice group (MusyX sound-effect group {d.sounds.group}): every clip the game plays for them. Click to play; each one downloads as a WAV.</p>
          <div class="clips">
            {#each d.sounds.samples as s}
              <div class="clip" class:on={playing === s.n}>
                <button class="play" onclick={() => play(s.n)} title={s.label}>{playing === s.n ? '⏹' : '▶'}</button>
                <span class="nm">Clip {s.n + 1}</span>
                <span class="dim small">{secs(s.seconds)}</span>
                <a class="small" href={urls.audioDownload(d.sounds.entry, s.n)}>WAV</a>
              </div>
            {/each}
          </div>
          <audio bind:this={player} onended={() => (playing = null)} style="display:none"></audio>
          <div class="row" style="margin-top:12px">
            <button onclick={() => exportAll('sounds')} disabled={exporting}>Export all clips as WAV</button>
            <a class="btn" href={urls.data(d.sounds.entry)}>Download sound group</a>
            <a href="#entry/{d.sounds.entry}" onclick={() => app.open(d!.sounds!.entry)} class="small">open in Browse assets</a>
          </div>
        {:else if section === 'files'}
          <p class="dim" style="margin-top:0">Every file the game's tables tie to this character. Download gives the decompressed file; Browse opens it with textures, hex and replacement.</p>
          <table>
            <thead><tr><th>what</th><th>for</th><th>type</th><th>size</th><th></th></tr></thead>
            <tbody>
              {#each d.files as f}
                <tr>
                  <td>{f.role}</td>
                  <td class="dim">{f.slot === null ? '' : d.variants.find(v => v.slot === f.slot)?.name ?? `slot ${f.slot}`}</td>
                  <td class="dim">{f.kind}{#if f.textures} · {f.textures} tex{/if}{#if f.audio} · {f.audio} clips{/if}</td>
                  <td class="dim">{kb(f.size)}</td>
                  <td><a href={urls.data(f.entry)}>download</a> · <a href="#entry/{f.entry}" onclick={() => app.open(f.entry)}>browse</a></td>
                </tr>
              {/each}
            </tbody>
          </table>
          <div class="row" style="margin-top:12px">
            <button onclick={() => exportAll('files')} disabled={exporting}>Export all files to a folder</button>
            <button onclick={() => exportAll('textures')} disabled={exporting}>Export textures as PNG</button>
          </div>
        {/if}
      </div>
    {/if}

    <details class="clonebox" bind:open={showClone}>
      <summary>Slot cloning <span class="dim">make one roster slot play as another character</span></summary>
      <div class="card" style="margin-top:8px">
        {#if !editable}
          <p class="warn" style="margin:0">Editing needs an extracted game with ZZZZ.dat and aaaa.dat. Use <a href="#game" onclick={() => app.go('game')}>Prepare for editing</a> on the Game page.</p>
        {:else}
          <div class="row">
            <label>Play as <select bind:value={source} disabled={busy}>{#each slots as s}<option value={s.slot}>{s.slot} · {s.name}</option>{/each}</select></label>
            <span class="dim">→</span>
            <label>in slot <select bind:value={target} disabled={busy}>{#each slots as s}<option value={s.slot} disabled={s.clone_of !== null}>{s.slot} · {s.name}{s.clone_of !== null ? ' (cloned)' : ''}</option>{/each}</select></label>
            <button class="primary" onclick={clone} disabled={busy || source === target}>Clone</button>
            <label class="dim"><input type="checkbox" bind:checked={copy} disabled={busy}> copy the files so the clone can be retextured on its own</label>
          </div>
          {#if cloned.length}
            <table style="margin-top:10px"><tbody>
              {#each cloned as s}<tr><td>{s.slot} · {s.name}</td><td>plays as <span class="ok">{s.clone_of_name}</span> <span class="dim">({s.copy ? 'copied files' : 'shared files'})</span></td><td><button class="danger" onclick={() => restore(s.slot)} disabled={busy}>Restore</button></td></tr>{/each}
            </tbody></table>
          {/if}
        {/if}
        {#if msg}<p class={ok ? 'ok' : busy ? 'dim' : 'warn'} style="margin:10px 0 0">{msg}</p>{/if}
      </div>
    </details>
  </section>
</div>

<style>
  .page { flex: 1; display: flex; min-height: 0; }
  aside { width: 230px; flex: none; overflow: auto; border-right: 1px solid var(--line); padding: 10px; background: var(--panel); }
  aside input { width: 100%; margin-bottom: 8px; }
  aside ul { list-style: none; margin: 0; padding: 0; }
  aside li button { width: 100%; display: flex; align-items: center; gap: 10px; background: none; border: none; padding: 5px 6px; border-radius: 6px; text-align: left; color: var(--fg); }
  aside li button:hover { background: var(--panel2); }
  aside li.on button { background: var(--sel); }
  .face { width: 34px; height: 34px; border-radius: 6px; overflow: hidden; flex: none; display: flex; align-items: center; justify-content: center; }
  .face img { max-width: 100%; max-height: 100%; image-rendering: pixelated; }
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
  .banks { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px; }
  .bank { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 10px; }
  .bank.on { border-color: var(--acc); background: var(--sel); }
  .bankbtn { background: none; border: none; padding: 0; text-align: left; width: 100%; }
  .seqs { max-height: 62px; overflow: hidden; margin: 2px 0 4px; }
  .small { font-size: 12px; }
  .clips { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 6px; }
  .clip { display: flex; align-items: center; gap: 8px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 5px 8px; }
  .clip.on { border-color: var(--acc); }
  .clip .nm { flex: 1; }
  .play { width: 30px; height: 30px; padding: 0; border-radius: 15px; }
  table { width: 100%; }
  td { padding: 4px 10px; }
  .clonebox { margin: auto 20px 16px; padding-top: 12px; }
  .clonebox summary { cursor: pointer; color: var(--dim); }
  .clonebox summary:hover { color: var(--fg); }
</style>
