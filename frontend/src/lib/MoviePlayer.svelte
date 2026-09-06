<script lang="ts">
  // HVQM4 movie playback: the audio element is the clock; frames are JPEGs
  // fetched by number and drawn on a canvas, a few seconds ahead.
  import { onMount } from 'svelte'
  import { api, urls, pollJob, type MovieInfo } from './api'

  let { entry }: { entry: number } = $props()
  let info = $state<MovieInfo | null>(null)
  let msg = $state('')
  let progress = $state(0)
  let busy = $state(false)
  let canvas: HTMLCanvasElement
  let audio: HTMLAudioElement
  let frame = $state(0)
  const cache = new Map<number, ImageBitmap>()
  let fetching = new Set<number>()
  let alive = true

  async function load() {
    try { info = await api.movie(entry) } catch (e: any) { msg = e.message }
    if (info?.job) watch(info.job)
  }
  async function prepare() {
    busy = true; msg = 'decoding…'
    try {
      const r = await api.prepareMovie(entry)
      if (r.job) await watch(r.job)
      else { info = await api.movie(entry) }
    } catch (e: any) { msg = e.message; busy = false }
  }
  async function watch(id: string) {
    busy = true
    const jb = await pollJob(id, api.job, j => (progress = j.progress))
    busy = false
    if (jb.state === 'error') { msg = jb.error ?? 'failed'; return }
    msg = ''; info = await api.movie(entry)
  }
  async function exportFrames() {
    msg = 'exporting…'
    try { const r = await api.exportMovie(entry); msg = `saved ${r.written.length} files to ${r.dest}` } catch (e: any) { msg = e.message }
  }
  function ensure(n: number) {
    if (!info?.frames || n < 0 || n >= info.frames || cache.has(n) || fetching.has(n)) return
    fetching.add(n)
    fetch(urls.movieFrame(entry, n)).then(r => r.blob()).then(createImageBitmap).then(b => { cache.set(n, b); fetching.delete(n) }).catch(() => fetching.delete(n))
  }
  function tick() {
    if (!alive) return
    requestAnimationFrame(tick)
    if (!info?.ready || !info.fps || !audio) return
    const n = Math.min(info.frames! - 1, Math.floor(audio.currentTime * info.fps))
    for (let k = n; k < n + Math.ceil(info.fps * 2); k++) ensure(k)
    for (const k of [...cache.keys()]) if (k < n - 5 || k > n + info.fps * 4) { cache.get(k)?.close(); cache.delete(k) }
    const bmp = cache.get(n) ?? cache.get(n - 1)
    if (bmp && n !== frame) {
      frame = n
      const ctx = canvas.getContext('2d')!
      if (canvas.width !== bmp.width) { canvas.width = bmp.width; canvas.height = bmp.height }
      ctx.drawImage(bmp, 0, 0)
    }
  }
  onMount(() => { load(); tick(); return () => { alive = false; for (const b of cache.values()) b.close() } })
  $effect(() => { entry; cache.clear(); frame = -1; info = null; load() })
</script>

{#if !info}
  <div class="dim">loading…</div>
{:else if !info.ready}
  <div class="card">
    {#if !info.helper}
      <p class="warn" style="margin:0">The movie decoder helper is not built. Run <code>python native/build_hvqm4.py</code> (needs clang or gcc) and restart; see the README's Movies section.</p>
    {:else}
      <p class="dim" style="margin:0 0 8px">Movies are decoded once into the cache (a few seconds for the short ones, under a minute for the intro), then play here.</p>
      <div class="row"><button class="primary" onclick={prepare} disabled={busy}>{busy ? `decoding… ${Math.round(progress * 100)}%` : 'Decode movie'}</button>{#if msg}<span class="warn">{msg}</span>{/if}</div>
    {/if}
  </div>
{:else}
  <div class="row" style="margin-bottom:8px">
    <span class="dim">{info.width}×{info.height} · {info.frames} frames · {info.fps?.toFixed(2)} fps · {info.sample_rate} Hz · frame {frame + 1}</span>
    <button onclick={exportFrames}>Export frames + WAV</button>
    {#if msg}<span class="dim">{msg}</span>{/if}
  </div>
  <canvas bind:this={canvas} style="width:100%;max-width:{info.width}px;display:block;background:#000;border-radius:6px"></canvas>
  <audio bind:this={audio} controls src={urls.movieAudio(entry)} style="width:100%;max-width:{info.width}px;margin-top:6px"></audio>
{/if}
