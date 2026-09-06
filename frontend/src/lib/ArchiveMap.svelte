<script lang="ts">
  // A strip map of ZZZZ.dat: every entry a block sized by its on-disc bytes
  // and coloured by kind, gaps dark. Hover names a block, click selects it.
  import { onMount } from 'svelte'
  import { app } from './state.svelte'
  import { hex, kb, KIND_LABEL, type EntrySummary } from './api'

  let { onpick }: { onpick: (id: number) => void } = $props()
  let canvas: HTMLCanvasElement
  let wrap: HTMLDivElement
  let zoom = $state(1)
  let hover = $state<{ e: EntrySummary | null; gap?: [number, number]; x: number } | null>(null)
  let width = $state(800)
  const H = 34

  const COLOURS: Record<string, string> = {
    container: '#3e6ea6', textures: '#3f8a52', anim: '#a6763e', hvqm4: '#8a3f7a', musyx: '#8a8a3e', songs: '#a6a63e',
    adgc: '#c9a23e', text: '#7a7a8a', unknown: '#4a4f5a', rel: '#5a5a5a',
  }
  const colour = (e: EntrySummary) => COLOURS[e.kind] ?? '#4a4f5a'

  const entries = $derived([...app.entries.values()].filter(e => e.archive === 'ZZZZ.dat').sort((a, b) => a.offset - b.offset))
  const total = $derived(Math.max(app.archiveSize, entries.reduce((m, e) => Math.max(m, e.offset + e.disc_size), 0)))
  // laid-out blocks: [x0, x1, entry|null]; gaps get null
  const blocks = $derived.by(() => {
    const out: { x0: number; x1: number; e: EntrySummary | null; off: number; len: number }[] = []
    const w = width * zoom
    let cur = 0
    for (const e of entries) {
      if (e.offset > cur) out.push({ x0: cur / total * w, x1: e.offset / total * w, e: null, off: cur, len: e.offset - cur })
      out.push({ x0: e.offset / total * w, x1: (e.offset + e.disc_size) / total * w, e, off: e.offset, len: e.disc_size })
      cur = Math.max(cur, e.offset + e.disc_size)
    }
    if (cur < total) out.push({ x0: cur / total * w, x1: w, e: null, off: cur, len: total - cur })
    return out
  })

  function draw() {
    if (!canvas || !total) return
    const w = Math.round(width * zoom), dpr = devicePixelRatio || 1
    canvas.width = w * dpr; canvas.height = H * dpr; canvas.style.width = w + 'px'; canvas.style.height = H + 'px'
    const g = canvas.getContext('2d')!
    g.scale(dpr, dpr)
    g.fillStyle = '#0f1115'; g.fillRect(0, 0, w, H)
    for (const b of blocks) {
      const x = Math.floor(b.x0), x1 = Math.max(x + 1, Math.ceil(b.x1))
      g.fillStyle = b.e ? colour(b.e) : '#1b1e24'
      g.fillRect(x, b.e ? 4 : 12, x1 - x, b.e ? H - 8 : H - 24)
      if (b.e && app.modified.includes(b.e.id)) { g.fillStyle = '#7ec8a0'; g.fillRect(x, 0, x1 - x, 3) }
    }
    if (app.selected !== null) {
      const b = blocks.find(b => b.e?.id === app.selected)
      if (b) { g.strokeStyle = '#ffffff'; g.lineWidth = 2; g.strokeRect(Math.floor(b.x0) + 1, 1, Math.max(2, Math.ceil(b.x1) - Math.floor(b.x0)) - 2, H - 2) }
    }
  }
  $effect(() => { blocks; app.selected; app.modified; draw() })
  onMount(() => {
    const ro = new ResizeObserver(() => { width = wrap.clientWidth || 800 })
    ro.observe(wrap)
    width = wrap.clientWidth || 800
    return () => ro.disconnect()
  })
  function at(x: number) {
    let lo = 0, hi = blocks.length - 1
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (blocks[mid].x0 <= x) lo = mid; else hi = mid - 1 }
    return blocks[lo]
  }
  function move(ev: MouseEvent) {
    const r = canvas.getBoundingClientRect()
    const b = at(ev.clientX - r.left)
    hover = b ? { e: b.e, gap: b.e ? undefined : [b.off, b.len], x: ev.clientX - wrap.getBoundingClientRect().left } : null
  }
  function click(ev: MouseEvent) {
    const r = canvas.getBoundingClientRect()
    const b = at(ev.clientX - r.left)
    if (b?.e) onpick(b.e.id)
  }
  const kindLabel = (e: EntrySummary) => KIND_LABEL[e.kind] ?? e.kind
  const legend = $derived([...new Set(entries.map(e => e.kind))].sort())
</script>

<div class="map">
  <div class="head">
    <span class="dim">ZZZZ.dat, {kb(total)}, in archive order · click a block to open it</span>
    <span style="flex:1"></span>
    {#each legend as k}<span class="key"><i style="background:{COLOURS[k] ?? '#4a4f5a'}"></i>{KIND_LABEL[k] ?? k}</span>{/each}
    <label class="dim">zoom <input type="range" min="1" max="64" step="1" bind:value={zoom} style="width:110px;vertical-align:middle"> {zoom}×</label>
  </div>
  <div class="wrap" bind:this={wrap}>
    <div class="scroll">
      <canvas bind:this={canvas} onmousemove={move} onmouseleave={() => (hover = null)} onclick={click}></canvas>
    </div>
    {#if hover}
      <div class="tip" style="left:{Math.min(hover.x, width - 260)}px">
        {#if hover.e}
          <b>{app.nameOf(hover.e)}</b><br><span class="dim">#{hover.e.id} · {kindLabel(hover.e)} · {hex(hover.e.offset)} · {kb(hover.e.disc_size)}{hover.e.compressed ? ' on disc' : ''}</span>
        {:else if hover.gap}
          <b>gap</b><br><span class="dim">{hex(hover.gap[0])} · {kb(hover.gap[1])} unindexed</span>
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .map { margin-bottom: 10px; }
  .head { display: flex; gap: 12px; align-items: center; font-size: 12px; margin-bottom: 4px; flex-wrap: wrap; }
  .key { display: inline-flex; align-items: center; gap: 4px; color: var(--dim); }
  .key i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
  .wrap { position: relative; }
  .scroll { overflow-x: auto; overflow-y: hidden; border: 1px solid var(--line); border-radius: 6px; }
  canvas { display: block; cursor: pointer; }
  .tip { position: absolute; top: 38px; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font-size: 12px; pointer-events: none; z-index: 2; white-space: nowrap; }
</style>
