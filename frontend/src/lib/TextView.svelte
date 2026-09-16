<script lang="ts">
  // The strings of a text table: decoded with the control words as tags, or
  // drawn with the game's own font pages; plus a search across every table.
  import { api, urls, type TextString } from './api'
  import { app } from './state.svelte'

  let { entry }: { entry: number } = $props()
  let strings = $state<TextString[] | null>(null)
  let hasFont = $state(false)
  let colours = $state<string[]>([])
  let filter = $state('')
  let showEmpty = $state(false)
  let drawn = $state(true)
  let style = $state(0)
  let everywhere = $state(false)
  let hits = $state<{ entry: number; n: number; text: string }[] | null>(null)
  let searching = $state(false)
  $effect(() => {
    const cur = entry
    strings = null; hits = null
    api.text(cur).then(r => { if (cur === entry) { strings = r.strings; hasFont = r.font; colours = r.colours; if (!r.font) drawn = false } })
  })
  $effect(() => {
    const q = filter.trim()
    if (!everywhere || q.length < 2) { hits = null; return }
    searching = true
    const t = setTimeout(() => api.textSearch(q).then(r => { if (filter.trim() === q) { hits = r.matches; searching = false } }), 250)
    return () => clearTimeout(t)
  })
  const shown = $derived.by(() => {
    if (!strings) return []
    const f = filter.toLowerCase()
    return strings.filter(s => (showEmpty || s.codes > 0) && (!f || s.text.toLowerCase().includes(f) || String(s.n) === f))
  })
  const dup = $derived.by(() => {
    if (!strings || strings.length < 4) return false
    let same = 0, pairs = 0
    for (let i = 0; i + 1 < strings.length; i += 2) { pairs++; if (strings[i].text === strings[i + 1].text) same++ }
    return same > pairs * 0.8
  })
  // strings that put no pixels on screen (a lone font switch, or nothing) show their tags instead of an empty image
  const drawable = (s: TextString) => s.tokens.some(([k, t]) => (k === 't' && t.trim() !== '') || k === 'g' || (k === 'c' && ['stick', 'A', 'B', 'X', 'Y', 'R', 'L', 'Z', 'note'].includes(t)) || t.startsWith('value'))
  const tagColour = (t: string) => { const i = ['', 'pink', 'gold', 'red', 'green', 'blue', 'dark red', 'teal', 'indigo', 'black'].indexOf(t); return i > 0 && colours[i] ? colours[i] : '' }
</script>

{#if !strings}
  <div class="dim">loading…</div>
{:else}
  <div class="row" style="margin-bottom:8px;flex-wrap:wrap">
    <input type="search" placeholder="find text or #" bind:value={filter} style="width:220px">
    <label class="dim" title="search every text table in the game, not only this one"><input type="checkbox" bind:checked={everywhere}> all tables</label>
    <label class="dim"><input type="checkbox" bind:checked={showEmpty}> empty strings</label>
    {#if hasFont}
      <label class="dim"><input type="checkbox" bind:checked={drawn}> as drawn</label>
      {#if drawn}<select bind:value={style} title="the font size a menu asks for"><option value={0}>large</option><option value={1}>small</option><option value={2}>small (2)</option><option value={3}>large (3)</option></select>{/if}
    {/if}
    <span class="dim">{shown.length} of {strings.length}</span>
    <span style="flex:1"></span>
    <a class="btn" href={urls.textTxt(entry)}>Download .txt</a>
  </div>
  <p class="dim" style="margin:0 0 8px">Strings are 16-bit words: glyph codes, and control words for line breaks, colours, controller icons, font switches, typing speed, inserted numbers and challenge-mode sound cues, decoded as the game's text engine does (the decomp's DrawText). "As drawn" renders each string with the game's font pages, widths and colour table{dup ? '. Every string appears twice in this table, one copy per text slot' : ''}.</p>
  {#if everywhere && filter.trim().length >= 2}
    <h3 style="margin:0 0 6px">Across all tables {#if searching}<span class="dim">searching…</span>{:else if hits}<span class="dim">{hits.length} match{hits.length === 1 ? '' : 'es'}{hits.length >= 200 ? ' (first 200)' : ''}</span>{/if}</h3>
    {#if hits}
      <table class="strings">
        <tbody>
          {#each hits as h}
            <tr><td class="dim n"><a href="#entry/{h.entry}" onclick={() => app.open(h.entry)} title="open this table">{h.entry === entry ? 'here' : app.nameOf(app.entries.get(h.entry)!) ?? h.entry}</a> #{h.n}</td><td class="t">{h.text}</td></tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {:else}
    <table class="strings">
      <tbody>
        {#each shown as s (s.n)}
          <tr><td class="dim n">{s.n}</td>
            <td class="t">
              {#if drawn && drawable(s)}<img class="drawn" loading="lazy" src={urls.textPng(entry, s.n, style)} alt={s.text} title={s.text}>{/if}
              {#if !drawn || !drawable(s)}{#each s.tokens as [k, t]}{#if k === 't'}{t}{:else}<span class="tag {k}" style={tagColour(t) ? `color:${tagColour(t)}` : ''} title={k === 'g' ? 'a cell of the proportional font, given directly' : k === '?' ? 'a code the text engine has no case for' : 'control word'}>{t}</span>{/if}{/each}{/if}
            </td></tr>
        {/each}
      </tbody>
    </table>
  {/if}
{/if}

<style>
  .strings { border-collapse: collapse; width: 100%; }
  .strings td { padding: 3px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
  .strings .n { width: 60px; text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .strings .t { white-space: pre-wrap; }
  .drawn { display: block; image-rendering: pixelated; max-width: 100%; background: #2d5a2d; padding: 2px 4px; border-radius: 3px; }
  .tag { display: inline-block; font-size: 10px; padding: 0 4px; margin: 0 1px; border-radius: 3px; background: var(--panel); color: var(--dim); border: 1px solid var(--line); vertical-align: middle; }
  .tag.g { color: #d8b45a; }
  .tag.\? { color: #e07070; }
</style>
