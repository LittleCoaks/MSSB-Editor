<script lang="ts">
  import { onMount } from 'svelte'
  import { app } from './state.svelte'
  import { api, urls, kb, native, pollJob, type MusicInfo, type Track, type Job } from './api'

  let info = $state<MusicInfo | null>(null)
  let file = $state<File | null>(null)
  let filePath = $state<string | null>(null)
  let track = $state('')
  let pad = $state(true)
  let over = $state(false)
  let job = $state<Job | null>(null)
  let msg = $state('')
  let step = $state<1 | 2>(1)

  async function load() { info = await api.music(); if (!track && info.tracks.length) track = info.tracks[0].file }
  onMount(load)

  function chose(f: File | null, p: string | null) { file = f; filePath = p; step = 2; job = null }
  async function pickNative(e: Event) {
    const n = native()
    if (!n) return  // let the <input type=file> open
    e.preventDefault()
    const p = await n.pick_audio()
    if (p) chose(null, p)
  }
  function drop(e: DragEvent) {
    e.preventDefault(); over = false
    const f = e.dataTransfer?.files[0]
    if (f) chose(f, null)
  }
  async function install() {
    if (!file && !filePath) return
    const fd = new FormData()
    if (file) fd.append('file', file); else fd.append('path', filePath!)
    fd.append('track', track); fd.append('pad', pad ? '1' : '0')
    msg = ''
    try {
      const { job: id } = await api.musicInstall(fd)
      job = await pollJob(id, api.musicJob, j => (job = j))
      await load()
      if (job.state === 'done') { file = null; filePath = null; step = 1 }
    } catch (e: any) { msg = e.message }
  }
  async function restore(t: Track) {
    try { await api.musicRestore(t.file); await load() } catch (e: any) { msg = e.message }
  }
  const status = (t: Track) => !t.exists ? 'not on disc' : t.modified ? 'replaced' : t.custom ? 'custom' : 'original'
  const sel = $derived(info?.tracks.find(t => t.file === track))
</script>

<div class="page">
  <h1>Music</h1>
  {#if !info}
    <div class="dim">loading…</div>
  {:else if !info.root}
    <div class="card warn">Your game is view only (a disc image). <a href="#game" onclick={() => app.go('game')}>Extract it to a folder</a> to replace music. You can still listen below.</div>
  {/if}

  {#if info?.root}
    <div class="card flow">
      <h2>Replace a track</h2>
      <div class="steps">
        <div class="step" class:done={step === 2}>
          <b>1. Pick your song</b>
          <div class="drop" class:over ondragover={e => { e.preventDefault(); over = true }} ondragleave={() => (over = false)} ondrop={drop} role="region" aria-label="drop audio">
            {#if file || filePath}
              <div>🎵 <b>{file ? file.name : filePath}</b>{#if file} <span class="dim">({kb(file.size)})</span>{/if}</div>
              <button style="margin-top:6px" onclick={() => chose(null, null)}>choose another</button>
            {:else}
              Drop an audio file here<br>
              <label class="btn" style="display:inline-block;margin-top:8px" onclick={pickNative}>Browse… <input type="file" accept="audio/*,.wav,.mp3,.flac,.ogg,.m4a,.aac,.opus,.wma" hidden onchange={e => chose((e.target as HTMLInputElement).files?.[0] ?? null, null)}></label>
              <div class="dim" style="font-size:12px;margin-top:6px">wav{info.backends.length ? ', mp3, flac, ogg' : ''}{info.backends.includes('ffmpeg') ? ', m4a, aac, opus, wma' : ''} · any sample rate, converted automatically</div>
            {/if}
          </div>
        </div>
        <div class="step">
          <b>2. Choose what it replaces</b>
          <select bind:value={track}>
            {#each info.tracks as t}<option value={t.file}>{t.label} ({t.category})</option>{/each}
          </select>
          {#if sel}
            <div class="dim" style="margin-top:6px">
              {#if sel.custom}Custom slots are silent until a mod points a stage at them; pick a real track to hear your song in game.
              {:else if sel.stock_size}The game expects this track to be {sel.seconds} s long. A shorter song is padded with silence; a longer one is cut unless you apply the patch shown after installing.
              {:else}Length is not checked for this track.{/if}
            </div>
          {/if}
          <label style="display:block;margin-top:6px"><input type="checkbox" bind:checked={pad}> pad shorter songs to the original length (recommended)</label>
        </div>
        <div class="step">
          <b>3. Install</b>
          <div class="row">
            <button class="primary" disabled={(!file && !filePath) || job?.state === 'running'} onclick={install}>Install</button>
            {#if job?.state === 'running'}<span class="bar"><i style="width:{Math.round(job.progress * 100)}%"></i></span> encoding {Math.round(job.progress * 100)}%{/if}
          </div>
          {#if job?.state === 'error'}<div class="warn">{job.error}</div>{/if}
          {#if job?.state === 'done'}
            <div class="ok" style="margin-top:6px">Installed over <b>{job.track}</b>: {job.result.seconds.toFixed(1)} s{job.result.resampled ? `, converted from ${job.result.source_rate} Hz` : ''}{job.result.padded ? ', padded to the original length' : ''}. The original was backed up; use “Restore” below to undo.</div>
            {#if job.result.truncated}<div class="warn">Your song is longer than the original, so the game will stop at the original length unless you apply this Gecko code:</div>{/if}
            {#if job.result.gecko?.length}<details><summary>Gecko code for the full length</summary><pre>{job.result.gecko.join('\n')}</pre></details>{/if}
          {/if}
          {#if msg}<div class="warn">{msg}</div>{/if}
        </div>
      </div>
      <div class="dim" style="font-size:12px;margin-top:8px">Encoder: {info.numpy ? 'fast (numpy)' : 'slow (install numpy for 30× faster encoding)'} · decoders: {info.backends.length ? info.backends.join(', ') : 'wav only (pip install miniaudio for mp3/flac/ogg)'}</div>
    </div>
  {/if}

  <h2 style="margin-top:18px">All tracks</h2>
  <table class="tracks">
    <thead><tr><th>Track</th><th>Type</th><th>Status</th><th>Length</th><th>Listen</th><th></th></tr></thead>
    <tbody>
      {#each info?.tracks ?? [] as t}
        <tr>
          <td><b>{t.label}</b><div class="dim" style="font-size:11px">{t.file}</div></td>
          <td class="dim">{t.category}</td>
          <td class:warn={t.mismatch} class:ok={t.modified}>{status(t)}{t.mismatch ? ' (length differs from what the game expects)' : ''}</td>
          <td>{t.exists ? t.seconds + ' s' : ''}</td>
          <td>{#if t.exists && t.entry !== null}<audio controls preload="none" src={urls.audio(t.entry, 0)} style="height:30px;width:260px"></audio>{/if}</td>
          <td>{#if t.modified}<button class="danger" onclick={() => restore(t)}>Restore original</button>{/if}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .page { padding: 20px 24px; overflow: auto; max-width: 1100px; }
  .flow { margin-top: 10px; }
  .steps { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 16px; }
  .step > b { display: block; margin-bottom: 8px; }
  .step select { width: 100%; }
  .tracks { width: 100%; }
  @media (max-width: 1000px) { .steps { grid-template-columns: 1fr; } }
</style>
