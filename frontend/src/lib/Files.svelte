<script lang="ts">
  // The raw entry table: every indexed file with its offsets, sizes and the
  // executable references it is loaded from. Sortable, filterable, and
  // clicking a row opens it in the detail panel.
  import { app } from './state.svelte'
  import { hex, kb, KIND_LABEL, type EntrySummary } from './api'
  import AssetDetail from './AssetDetail.svelte'
  import ArchiveMap from './ArchiveMap.svelte'

  type Col = { key: keyof EntrySummary | 'name'; label: string; num?: boolean; width?: string }
  const cols: Col[] = [
    { key: 'id', label: 'id', num: true }, { key: 'offset', label: 'offset', num: true }, { key: 'size', label: 'size', num: true },
    { key: 'disc_size', label: 'on disc', num: true }, { key: 'kind', label: 'kind' }, { key: 'ntex', label: 'tex', num: true },
    { key: 'naud', label: 'aud', num: true }, { key: 'name', label: 'name' }, { key: 'module', label: 'module' }, { key: 'symbol', label: 'symbol' },
  ]
  let sortKey = $state<Col['key']>('id')
  let sortDesc = $state(false)
  let filter = $state('')
  let kind = $state('')
  let archive = $state('')
  let onlyModified = $state(false)
  let shown = $state(300)
  let byPlace = $state(false)   // archive order: ZZZZ.dat by offset, gaps shown as rows

  const all = $derived([...app.entries.values()])
  const kinds = $derived([...new Set(all.map(e => e.kind))].sort())
  const archives = $derived([...new Set(all.map(e => e.archive))].sort())
  const q = $derived(filter.trim().toLowerCase())
  const rows = $derived.by(() => {
    let list = all
    if (kind) list = list.filter(e => e.kind === kind)
    if (archive) list = list.filter(e => e.archive === archive)
    if (onlyModified) list = list.filter(e => app.modified.includes(e.id))
    if (q) {
      const isHex = /^0x[0-9a-f]+$/.test(q)
      list = list.filter(e => String(e.id) === q || (isHex && e.offset === parseInt(q, 16)) || app.nameOf(e).toLowerCase().includes(q)
        || e.known.toLowerCase().includes(q) || e.label.toLowerCase().includes(q) || e.symbol.toLowerCase().includes(q)
        || e.names.some(n => n.toLowerCase().includes(q)) || e.refs.some(r => r.toLowerCase().includes(q)))
    }
    if (byPlace) return list.filter(e => e.archive === 'ZZZZ.dat').sort((a, b) => a.offset - b.offset)
    const key = sortKey
    const val = (e: EntrySummary) => key === 'name' ? app.nameOf(e).toLowerCase() : (e as any)[key]
    list = [...list].sort((a, b) => {
      const x = val(a), y = val(b)
      const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))
      return sortDesc ? -c : c
    })
    return list
  })
  $effect(() => { q; kind; archive; onlyModified; sortKey; sortDesc; byPlace; shown = 300 })
  // in archive order, a gap between consecutive entries becomes a row of its own
  type Row = { e: EntrySummary } | { gap: [number, number] }
  const placed = $derived.by((): Row[] => {
    if (!byPlace) return rows.map(e => ({ e }))
    const out: Row[] = []
    let cur = 0
    for (const e of rows) {
      if (!q && !kind && !onlyModified && e.offset > cur) out.push({ gap: [cur, e.offset - cur] })
      out.push({ e }); cur = Math.max(cur, e.offset + e.disc_size)
    }
    return out
  })
  const visible = $derived(placed.slice(0, shown))
  function jumpTo(id: number) { app.selected = id; byPlace = true; filter = ''; kind = ''; onlyModified = false
    const i = placed.findIndex(r => 'e' in r && r.e.id === id); if (i >= shown) shown = i + 200
    queueMicrotask(() => document.getElementById('file-' + id)?.scrollIntoView({ block: 'center' })) }
  function sortBy(k: Col['key']) { if (sortKey === k) sortDesc = !sortDesc; else { sortKey = k; sortDesc = false } }
  const kindLabel = (e: EntrySummary) => e.archive === 'disc' ? 'music' : (KIND_LABEL[e.kind] ?? e.kind)
</script>

<div class="files">
  <section class="list" class:narrow={app.selected !== null}>
    <div class="row" style="margin-bottom:10px">
      <input type="search" placeholder="Filter by id, 0xoffset, name, symbol, reference…" bind:value={filter} style="width:320px">
      <select bind:value={kind}><option value="">all kinds</option>{#each kinds as k}<option value={k}>{k}</option>{/each}</select>
      <select bind:value={archive}><option value="">all archives</option>{#each archives as a}<option value={a}>{a}</option>{/each}</select>
      <label><input type="checkbox" bind:checked={onlyModified}> replaced only</label>
      <label title="ZZZZ.dat in the order the files sit in it, gaps included"><input type="checkbox" bind:checked={byPlace}> archive order</label>
      <span class="dim">{rows.length} of {all.length} files</span>
    </div>
    <ArchiveMap onpick={jumpTo} />
    <div class="tablewrap">
      <table>
        <thead><tr>
          {#each cols as c}<th class:num={c.num} onclick={() => sortBy(c.key)} class:on={sortKey === c.key}>{c.label}{#if sortKey === c.key}{sortDesc ? ' ▼' : ' ▲'}{/if}</th>{/each}
        </tr></thead>
        <tbody>
          {#each visible as r ('e' in r ? r.e.id : 'gap' + r.gap[0])}
            {#if 'gap' in r}
              <tr class="gap"><td></td><td class="num mono">{hex(r.gap[0])}</td><td class="num">{kb(r.gap[1])}</td><td colspan="7" class="dim">gap, not indexed</td></tr>
            {:else}
            {@const e = r.e}
            <tr id="file-{e.id}" class:on={app.selected === e.id} class:mod={app.modified.includes(e.id)} onclick={() => (app.selected = e.id)} title={e.refs.join('\n')}>
              <td class="num">{e.id}</td>
              <td class="num mono">{hex(e.offset)}</td>
              <td class="num" title={hex(e.size)}>{kb(e.size)}</td>
              <td class="num" title={e.compressed ? `LZSS L=${e.lookback_bits} R=${e.repeat_bits}` : 'stored'}>{e.compressed ? kb(e.disc_size) : '–'}</td>
              <td><span class="badge {kindLabel(e).replace(' ', '-')}">{kindLabel(e)}</span></td>
              <td class="num">{e.ntex || ''}</td>
              <td class="num">{e.naud || ''}</td>
              <td>{#if app.modified.includes(e.id)}<span class="ok" title="replaced">● </span>{/if}{app.nameOf(e)}</td>
              <td class="dim">{e.module}</td>
              <td class="mono dim">{e.symbol}</td>
            </tr>
            {/if}
          {/each}
        </tbody>
      </table>
      {#if shown < placed.length}
        <div style="text-align:center;margin:14px 0"><button onclick={() => (shown += 600)}>Show more ({placed.length - shown} left)</button></div>
      {/if}
    </div>
  </section>
  {#if app.selected !== null}
    <section class="detail">
      <AssetDetail id={app.selected} onclose={() => (app.selected = null)} />
    </section>
  {/if}
</div>

<style>
  .files { flex: 1; display: flex; min-height: 0; }
  .list { flex: 1; min-width: 0; display: flex; flex-direction: column; padding: 12px 16px; }
  .tablewrap { overflow: auto; flex: 1; }
  table { width: 100%; font-size: 13px; }
  th { position: sticky; top: 0; background: var(--panel); cursor: pointer; user-select: none; white-space: nowrap; }
  th.on { color: var(--fg); }
  td { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 260px; }
  .num { text-align: right; }
  .mono { font-family: ui-monospace, Consolas, monospace; }
  tr { cursor: pointer; }
  tbody tr:hover { background: var(--panel2); }
  tr.gap { cursor: default; color: var(--dim); background: #0f1115; }
  tbody tr.on { background: var(--panel2); outline: 1px solid var(--acc); }
  .detail { flex: 1; min-width: 0; overflow: auto; border-left: 1px solid var(--line); }
  .list.narrow { flex: 0 0 46%; } .list.narrow td { max-width: 160px; }
</style>
