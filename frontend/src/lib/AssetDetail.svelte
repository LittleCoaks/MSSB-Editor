<script lang="ts">
  import { api, urls, kb, hex, friendlyName, KIND_LABEL, type EntryDetail } from './api'
  import { app } from './state.svelte'
  import ModelViewer from './ModelViewer.svelte'

  let { id, onclose }: { id: number; onclose: () => void } = $props()
  let d = $state<EntryDetail | null>(null)
  let tab = $state('')
  let msg = $state('')
  let hexOff = $state(0)
  let hexText = $state('')
  let bigTex = $state<number | null>(null)
  let playing = $state<number | null>(null)
  let playGen = $state(0)

  $effect(() => {
    const cur = id
    d = null; msg = ''; bigTex = null; playing = null
    api.entry(cur).then(x => { if (cur === id) { d = x; tab = x.models.length ? 'model' : x.textures.length ? 'textures' : x.audio.length ? 'audio' : 'details' } })
  })
  $effect(() => { if (tab === 'hex' && d) loadHex() })

  async function loadHex() {
    const r = await api.hex(d!.id, hexOff)
    const b = r.hex.match(/../g) ?? []
    let out = ''
    for (let i = 0; i < b.length; i += 16) {
      const row = b.slice(i, i + 16)
      out += (r.offset + i).toString(16).padStart(8, '0') + '  ' + row.join(' ').padEnd(47) + '  ' + row.map(x => { const c = parseInt(x, 16); return c >= 32 && c < 127 ? String.fromCharCode(c) : '.' }).join('') + '\n'
    }
    hexText = out || '(end of file)'
  }
  async function extract(opts: { png?: boolean; wav?: boolean; model?: string }) {
    msg = 'exporting…'
    try { const r = await api.extract(d!.id, opts); msg = `saved ${r.written.length} file(s) to ${r.written[0].replace(/[\\/][^\\/]*$/, '')}` } catch (e: any) { msg = e.message }
  }
  const kindLabel = (k: string) => KIND_LABEL[k] ?? k
  let replacing = $state(false)
  let editMsg = $state('')
  async function replaceWith(f: File | null) {
    if (!f || !d) return
    replacing = true; editMsg = 'writing…'
    try {
      const fd = new FormData(); fd.append('file', f)
      const r = await api.replace(d.id, fd)
      editMsg = `Replaced: ${kb(r.size)} (${kb(r.disc_size)} on disc, ${r.in_place ? 'written in place' : 'appended to ZZZZ.dat'}, ${r.descriptors} reference${r.descriptors === 1 ? '' : 's'} updated). The original is backed up.`
      await app.refresh(); d = await api.entry(d.id)
    } catch (e: any) { editMsg = e.message } finally { replacing = false }
  }
  let texMsg = $state('')
  let texBusy = $state(false)
  let texGen = $state(0)  // bumps so <img> tags reload after a replacement
  async function replaceTexture(n: number, f: File | null) {
    if (!f || !d) return
    texBusy = true; texMsg = 'encoding…'
    try {
      const fd = new FormData(); fd.append('file', f)
      const r = await api.replaceTexture(d.id, n, fd)
      const t = r.texture
      texMsg = `Replaced texture #${n} (${t.width}×${t.height} ${t.fmt}${t.levels > 1 ? `, ${t.levels} mip levels` : ''}${t.resized ? `, resized from ${t.source_width}×${t.source_height}` : ''}${t.palette ? `, ${t.palette}-colour palette` : ''}${t.truncated ? `; the last ${t.truncated} bytes of the encoding did not fit the room the file reserves and were dropped` : ''}). The original file is backed up.`
      await app.refresh(); d = await api.entry(d.id); texGen++
    } catch (e: any) { texMsg = e.message } finally { texBusy = false }
  }
  async function restoreEntry() {
    if (!d) return
    try { await api.restoreEntry(d.id); editMsg = 'Original restored.'; await app.refresh(); d = await api.entry(d.id) } catch (e: any) { editMsg = e.message }
  }
  const modified = $derived(app.modified.includes(id))
</script>

<div class="wrap">
  {#if !d}
    <div class="dim" style="padding:16px">loading…</div>
  {:else}
    <div class="head">
      <div>
        <h2>{app.nameOf(d)}</h2>
        <div class="dim">
          <span class="badge {kindLabel(d.kind).replace(' ', '-')}">{d.archive === 'disc' ? 'music' : kindLabel(d.kind)}</span>
          {#if d.textures.length} · {d.textures.length} textures{/if}{#if d.models.length} · {d.models.reduce((s, m) => s + m.triangles, 0).toLocaleString()} triangles{/if}{#if d.audio.length} · {d.audio.map(a => a.seconds + ' s').join(', ')}{/if}
          · {kb(d.size)}
        </div>
      </div>
      <button onclick={onclose} title="close">✕</button>
    </div>

    <div class="tabs">
      {#if d.models.length}<button class:on={tab === 'model'} onclick={() => (tab = 'model')}>3D model</button>{/if}
      {#if d.textures.length}<button class:on={tab === 'textures'} onclick={() => (tab = 'textures')}>Textures</button>{/if}
      {#if d.audio.length}<button class:on={tab === 'audio'} onclick={() => (tab = 'audio')}>Audio</button>{/if}
      <button class:on={tab === 'details'} onclick={() => (tab = 'details')}>Details</button>
      <button class:on={tab === 'hex'} onclick={() => (tab = 'hex')}>Hex</button>
      <span style="flex:1"></span>
      <div class="row">
        {#if d.textures.length}<button onclick={() => extract({ png: true })}>Export PNGs</button>{/if}
        {#if d.models.length}<button onclick={() => extract({ model: 'both' })}>Export model</button>{/if}
        {#if d.audio.length}<button onclick={() => extract({ wav: true })}>Export WAV</button>{/if}
        <a class="btn" href={urls.data(d.id)}>Raw file</a>
      </div>
    </div>
    {#if msg}<div class="dim" style="padding:0 16px 6px">{msg}</div>{/if}

    <div class="body">
      {#if tab === 'model'}
        <ModelViewer entry={d.id} models={d.models} banks={d.banks} />
      {:else if tab === 'textures'}
        {#if bigTex !== null}
          <div class="big">
            <button onclick={() => (bigTex = null)}>← back</button>
            <span class="dim">#{bigTex} · {d.textures[bigTex].width}×{d.textures[bigTex].height} {d.textures[bigTex].fmt}</span>
            <a class="btn" href={urls.tex(d.id, bigTex)} download>Download PNG</a>
            {#if app.game?.edit_ready && d.archive === 'ZZZZ.dat'}
              <label class="btn">Replace with PNG… <input type="file" accept="image/png,.png" hidden disabled={texBusy} onchange={e => { const el = e.target as HTMLInputElement; replaceTexture(bigTex!, el.files?.[0] ?? null); el.value = '' }}></label>
            {/if}
            {#if modified}<button class="danger" onclick={restoreEntry}>Restore original file</button>{/if}
            {#if texMsg}<div class={texMsg.startsWith('Replaced') ? 'ok' : texMsg === 'encoding…' ? 'dim' : 'warn'} style="margin-top:6px">{texMsg}</div>{/if}
            {#if app.game?.edit_ready && d.archive === 'ZZZZ.dat'}<div class="dim" style="margin-top:4px">The PNG is converted to this texture's size and format ({d.textures[bigTex].width}×{d.textures[bigTex].height} {d.textures[bigTex].fmt}); a different size is resampled to fit.</div>{/if}
            <div class="checker" style="margin-top:8px;display:inline-block"><img src={urls.tex(d.id, bigTex) + '?v=' + texGen} alt="" style="max-width:100%;image-rendering:pixelated"></div>
          </div>
        {:else}
          <div class="texgrid">
            {#each d.textures as t}
              <button class="tex" onclick={() => (bigTex = t.n)}>
                <div class="checker"><img loading="lazy" src={urls.tex(d.id, t.n) + '?v=' + texGen} alt="" style="max-width:128px;max-height:128px"></div>
                <span class="dim">{t.width}×{t.height} {t.fmt}</span>
              </button>
            {/each}
          </div>
        {/if}
      {:else if tab === 'audio'}
        {#if d.group}
          <p class="dim" style="margin-top:0">MusyX {d.group.kind} group {d.group.id}: {d.group.samples} samples{d.group.sfx ? `, ${d.group.sfx} sound effects` : ''}. Each sound effect is a macro that plays one of the samples below.</p>
          {#if d.sfx.length}
            <div class="sfxgrid">
              {#each d.sfx as f}
                <button class="sfx" disabled={!f.streams.length} title={`macro ${hex(f.macro, 4)}${f.streams.length ? '' : ' (plays through a layer; no direct sample)'}`} onclick={() => { if (f.streams.length) { playing = f.streams[0]; playGen++ } }}>▶ sfx {hex(f.id, 4)}{#if f.streams.length > 1}<span class="dim"> ×{f.streams.length}</span>{/if}</button>
              {/each}
            </div>
            {#if playing !== null}
              <div class="card" style="margin:8px 0">
                <div class="row"><b>Playing sample {playing + 1}</b> <span class="dim">{d.audio[playing].label}</span></div>
                {#key playGen}<audio controls autoplay src={urls.audio(d.id, playing)} style="width:100%;margin-top:6px"></audio>{/key}
              </div>
            {/if}
          {/if}
        {/if}
        {#each d.audio as s, n}
          <div class="card" style="margin-bottom:10px">
            <div class="row"><b>{s.kind === 'musyx' ? `Sample ${n + 1}` : `Stream ${n + 1}`}</b> {#if s.label}<span class="dim">{s.label}</span>{/if} <span class="dim">{s.rate} Hz · {s.channels === 2 ? 'stereo' : 'mono'} · {s.seconds} s{s.loop ? ' · loops' : ''}{s.note !== undefined && s.note !== 60 ? ` · base note ${s.note}` : ''}</span> <a href={urls.audioDownload(d.id, n)}>download WAV</a></div>
            <audio controls preload={s.kind === 'musyx' ? 'none' : 'metadata'} src={urls.audio(d.id, n)} style="width:100%;margin-top:6px"></audio>
          </div>
        {/each}
      {:else if tab === 'details'}
        <table>
          <tbody>
            <tr><th>Location</th><td>{d.archive} at {hex(d.offset)}</td></tr>
            <tr><th>Size</th><td>{kb(d.size)} ({hex(d.size)}), {d.compressed ? `LZSS compressed to ${kb(d.disc_size)}` : 'stored uncompressed'}</td></tr>
            <tr><th>Loaded by</th><td>{d.refs.join(', ')}</td></tr>
            {#if d.known}<tr><th>Community name</th><td>{d.known}</td></tr>{/if}
            {#if d.names.length}<tr><th>Embedded names</th><td>{d.names.join(', ')}</td></tr>{/if}
            {#if d.hvqm4}<tr><th>Movie</th><td>{d.hvqm4.width}×{d.hvqm4.height}, {d.hvqm4.video_frames} frames at {d.hvqm4.fps} fps, audio {d.hvqm4.audio_hz} Hz</td></tr>{/if}
            <tr><th>Export name</th><td>{d.file_name}</td></tr>
          </tbody>
        </table>
        {#if d.sections.length}
          <h3 style="margin-top:14px">Sections</h3>
          <table><thead><tr><th>#</th><th>offset</th><th>size</th><th>type</th><th>contents</th></tr></thead><tbody>
            {#each d.sections as s}
              <tr><td>{s.index}</td><td>{hex(s.offset)}</td><td>{kb(s.size)}</td><td>{hex(s.magic)}</td><td>{s.kind}{s.ntex ? ` (${s.ntex} textures)` : ''}</td></tr>
            {/each}
          </tbody></table>
        {/if}
        <h3 style="margin-top:16px">Replace</h3>
        {#if !app.game?.edit_ready}
          <p class="dim">To replace files, the game needs to be extracted with ZZZZ.dat and aaaa.dat. Use <a href="#game" onclick={() => app.go('game')}>Prepare for editing</a> on the Game page.</p>
        {:else}
          <p class="dim">Swap this file's raw contents ({kb(d.size)}, the same format as "Raw file"). It is compressed and the game's references are repointed automatically; if it doesn't fit its old slot it is appended to the archive. Single textures can be swapped from the Textures tab; models still have to be edited in the raw format for now.</p>
          <div class="row">
            <label class="btn">Choose replacement file… <input type="file" hidden onchange={e => replaceWith((e.target as HTMLInputElement).files?.[0] ?? null)} disabled={replacing}></label>
            {#if modified}<button class="danger" onclick={restoreEntry}>Restore original</button>{/if}
            {#if editMsg}<span class={editMsg.startsWith('Replaced') || editMsg.startsWith('Original') ? 'ok' : 'warn'}>{editMsg}</span>{/if}
          </div>
        {/if}
        <p class="dim" style="margin-top:14px">Every indexed file with offsets and references is listed under <a href="#files" onclick={() => app.go('files')}>All files</a>.</p>
      {:else if tab === 'hex'}
        <div class="row" style="margin-bottom:8px">
          <button onclick={() => { hexOff = Math.max(0, hexOff - 4096); loadHex() }}>◀</button>
          <input type="text" value={hex(hexOff)} onkeydown={e => { if (e.key === 'Enter') { hexOff = parseInt((e.target as HTMLInputElement).value, 16) || 0; loadHex() } }} style="width:120px">
          <button onclick={() => { hexOff += 4096; loadHex() }}>▶</button>
          <span class="dim">of {kb(d.size)}</span>
        </div>
        <pre>{hexText}</pre>
      {/if}
    </div>
  {/if}
</div>

<style>
  .wrap { display: flex; flex-direction: column; height: 100%; }
  .head { display: flex; justify-content: space-between; align-items: flex-start; padding: 14px 16px 6px; }
  .tabs { display: flex; gap: 4px; align-items: center; padding: 0 16px 8px; border-bottom: 1px solid var(--line); }
  .tabs > button { background: none; border: none; border-bottom: 2px solid transparent; color: var(--dim); border-radius: 0; }
  .tabs > button.on { color: var(--fg); border-bottom-color: var(--acc); }
  .body { padding: 12px 16px; overflow: auto; flex: 1; }
  .texgrid { display: flex; flex-wrap: wrap; gap: 8px; }
  .tex { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 6px; background: var(--panel); }
  .tex .checker { display: inline-block; }
  .big .checker { max-width: 100%; }
  .sfxgrid { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
  .sfx { padding: 4px 8px; font-size: 12px; font-family: ui-monospace, Consolas, monospace; }
</style>
