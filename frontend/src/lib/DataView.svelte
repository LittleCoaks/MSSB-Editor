<script lang="ts">
  // A structured look at a file nothing decodes: bytes laid out in rows of a
  // stride (guessed from how the bytes repeat) and read as bytes, shorts,
  // words or floats per column.
  import { api, hex, type StructInfo } from './api'

  let { entry, size }: { entry: number; size: number } = $props()
  let info = $state<StructInfo | null>(null)
  let stride = $state(16)
  let mode = $state('auto')
  let offset = $state(0)
  let bytes = $state<Uint8Array | null>(null)
  let busy = $state(false)
  const CHUNK = 16384

  $effect(() => {
    const cur = entry
    info = null; bytes = null; offset = 0
    api.struct(cur).then(i => { if (cur === entry) { info = i; stride = i.stride; load() } })
  })

  async function load() {
    busy = true
    try {
      const r = await api.hex(entry, offset, CHUNK)
      const m = r.hex.match(/../g) ?? []
      bytes = Uint8Array.from(m, x => parseInt(x, 16))
    } finally { busy = false }
  }
  async function setStride(s: number) {
    if (!(s > 0)) return
    stride = s
    if (s % 4 === 0) info = await api.struct(entry, s)
  }

  const view = $derived.by(() => bytes ? new DataView(bytes.buffer) : null)
  const rows = $derived(bytes ? Math.ceil(bytes.length / stride) : 0)
  // the columns of one row: [byte offset, width, kind]
  const cols = $derived.by((): [number, number, string][] => {
    const out: [number, number, string][] = []
    if (mode === 'auto' && info && stride % 4 === 0 && info.columns.length === stride / 4) {
      for (let c = 0; c < stride; c += 4) {
        const k = info.columns[c / 4]
        if (k === 'f32') out.push([c, 4, 'f32'])
        else if (k === 's16') out.push([c, 2, 's16'], [c + 2, 2, 's16'])
        else out.push([c, 1, 'u8'], [c + 1, 1, 'u8'], [c + 2, 1, 'u8'], [c + 3, 1, 'u8'])
      }
      return out
    }
    const w = mode === 'u8' || mode === 'auto' ? 1 : mode === 's16' || mode === 'u16' ? 2 : 4
    const k = mode === 'auto' ? 'u8' : mode
    for (let c = 0; c + w <= stride; c += w) out.push([c, w, k])
    for (let c = Math.floor(stride / w) * w; c < stride; c++) out.push([c, 1, 'u8'])
    return out
  })
  function cell(r: number, c: number, w: number, k: string): string {
    const o = r * stride + c
    if (!view || o + w > view.byteLength) return ''
    switch (k) {
      case 'f32': { const v = view.getFloat32(o); return Number.isFinite(v) ? (Math.abs(v) >= 1e6 || (v !== 0 && Math.abs(v) < 1e-4) ? v.toExponential(3) : +v.toFixed(4) + '') : 'NaN' }
      case 's16': return view.getInt16(o).toString()
      case 'u16': return view.getUint16(o).toString()
      case 's32': return view.getInt32(o).toString()
      case 'u32': return view.getUint32(o).toString()
      default: return view.getUint8(o).toString(16).padStart(2, '0')
    }
  }
</script>

<div class="row" style="margin-bottom:8px;flex-wrap:wrap">
  <label>stride <input type="number" min="1" max="4096" value={stride} style="width:70px" onchange={e => setStride(parseInt((e.target as HTMLInputElement).value))}></label>
  {#if info?.strides.length}
    <span class="dim">guess:</span>
    {#each info.strides.filter(s => s.score > 0.05).slice(0, 4) as s}
      <button class:on={s.stride === stride} onclick={() => setStride(s.stride)} title="how strongly the bytes repeat at this stride: {(s.score * 100).toFixed(0)}%">{s.stride}</button>
    {/each}
  {/if}
  <label>read as <select bind:value={mode}>
    <option value="auto">guess per column</option><option value="u8">bytes (hex)</option><option value="s16">s16</option><option value="u16">u16</option>
    <option value="s32">s32</option><option value="u32">u32</option><option value="f32">float</option></select></label>
  <span style="flex:1"></span>
  <button disabled={offset === 0} onclick={() => { offset = Math.max(0, offset - CHUNK); load() }}>◀</button>
  <input type="text" value={hex(offset)} style="width:110px" onkeydown={e => { if (e.key === 'Enter') { const v = parseInt((e.target as HTMLInputElement).value, 16) || 0; offset = Math.min(Math.max(0, v), size); offset -= offset % stride; load() } }}>
  <button disabled={offset + CHUNK >= size} onclick={() => { offset += CHUNK; load() }}>▶</button>
  <span class="dim">of {hex(size)}{busy ? ' · loading…' : ''}</span>
</div>
<p class="dim" style="margin:0 0 8px">Nothing in the game code has been matched to this file yet. The stride is where its bytes repeat, which is usually the record size of a table; the column guesses read each 4-byte column as floats when every row parses as one. Records that mix sizes will look misaligned.</p>
{#if bytes && cols.length}
  <div style="overflow:auto">
    <table class="data">
      <thead><tr><th>offset</th>{#each cols as [c, , k]}<th class={k}>{c.toString(16)}</th>{/each}</tr></thead>
      <tbody>
        {#each { length: rows } as _, r}
          <tr><td class="off">{(offset + r * stride).toString(16).padStart(6, '0')}</td>{#each cols as [c, w, k]}<td class={k}>{cell(r, c, w, k)}</td>{/each}</tr>
        {/each}
      </tbody>
    </table>
  </div>
{:else if !busy}
  <p class="dim">(empty)</p>
{/if}

<style>
  .data { font-family: ui-monospace, Consolas, monospace; font-size: 11px; border-collapse: collapse; white-space: nowrap; }
  .data th, .data td { padding: 1px 5px; text-align: right; border-bottom: 1px solid var(--line); }
  .data th { color: var(--dim); font-weight: normal; }
  .data .off { color: var(--dim); }
  .data td.f32 { color: #6cb0ff; }
  .data td.s16, .data td.u16, .data td.s32, .data td.u32 { color: #d8b45a; }
  button.on { border-color: var(--acc); color: var(--fg); }
</style>
