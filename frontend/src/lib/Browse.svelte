<script lang="ts">
  import { app } from './state.svelte'
  import { friendlyName, KIND_LABEL, urls, type EntrySummary } from './api'
  import AssetDetail from './AssetDetail.svelte'

  const cats = $derived(app.catalog?.categories ?? [])
  const cat = $derived(cats.find(c => c.id === app.category) ?? cats[0])
  const groups = $derived(cat?.groups ?? [])
  const grp = $derived(groups.find(g => g.id === app.group))

  const q = $derived(app.search.trim().toLowerCase())
  const items = $derived.by((): EntrySummary[] => {
    let ids: number[]
    if (q) ids = [...app.entries.keys()]
    else if (grp) ids = grp.items
    else ids = groups.flatMap(g => g.items)
    let list = ids.map(id => app.entries.get(id)!).filter(Boolean)
    if (q) list = list.filter(e => app.nameOf(e).toLowerCase().includes(q) || e.names.some(n => n.toLowerCase().includes(q)) || String(e.id) === q || e.symbol.toLowerCase().includes(q))
    return list.slice(0, 600)
  })
  const kindLabel = (e: EntrySummary) => e.archive === 'disc' ? 'music' : (KIND_LABEL[e.kind] ?? e.kind)
</script>

<div class="browse">
  <aside>
    <input type="search" placeholder="Search everything…" bind:value={app.search}>
    {#each cats as c}
      <div class="cat" class:on={c.id === app.category}>
        <button class="cathead" onclick={() => { app.category = c.id; app.group = ''; app.search = '' }}>{c.name} <span class="dim">{c.count}</span></button>
        {#if c.id === app.category && !q}
          <ul>
            <li class:on={!app.group}><button onclick={() => (app.group = '')}>All</button></li>
            {#each c.groups as g}
              <li class:on={g.id === app.group}><button onclick={() => (app.group = g.id)}>{g.name} <span class="dim">{g.items.length}</span></button></li>
            {/each}
          </ul>
        {/if}
      </div>
    {/each}
  </aside>

  <section class="grid" class:narrow={app.selected !== null}>
    <div class="crumbs">
      {#if q}Search results for “{app.search}”{:else}{cat?.name}{#if grp} › {grp.name}{/if}{/if}
      <span class="dim"> · {items.length === 600 ? 'first 600 of ' : ''}{q ? items.length : (grp ? grp.items.length : groups.reduce((s, g) => s + g.items.length, 0))} items</span>
    </div>
    <div class="cards">
      {#each items as e (e.id)}
        <button class="item" class:on={app.selected === e.id} onclick={() => (app.selected = e.id)} title={e.symbol}>
          <div class="thumb checker">
            {#if e.ntex}<img loading="lazy" src={urls.tex(e.id, e.thumb)} alt="">{:else}<span class="noimg">{kindLabel(e) === 'music' ? '🎵' : kindLabel(e) === 'movie' ? '🎬' : kindLabel(e) === 'animation' ? '🏃' : '▫'}</span>{/if}
          </div>
          <div class="name">{#if app.modified.includes(e.id)}<span title="replaced" class="ok">● </span>{/if}{app.nameOf(e)}</div>
          <div class="meta"><span class="badge {kindLabel(e).replace(' ', '-')}">{kindLabel(e)}</span>{#if e.ntex}<span class="dim">{e.ntex} tex</span>{/if}</div>
        </button>
      {/each}
    </div>
  </section>

  {#if app.selected !== null}
    <section class="detail">
      <AssetDetail id={app.selected} onclose={() => (app.selected = null)} />
    </section>
  {/if}
</div>

<style>
  .browse { flex: 1; display: flex; min-height: 0; }
  aside { width: 250px; flex: none; overflow: auto; border-right: 1px solid var(--line); padding: 10px; background: var(--panel); }
  aside input { width: 100%; margin-bottom: 10px; }
  .cathead { width: 100%; text-align: left; background: none; border: none; padding: 6px 8px; font-weight: 600; border-radius: 6px; }
  .cat.on .cathead { background: var(--panel2); }
  aside ul { list-style: none; margin: 2px 0 6px; padding: 0 0 0 10px; }
  aside li button { width: 100%; text-align: left; background: none; border: none; padding: 3px 8px; color: var(--dim); border-radius: 4px; }
  aside li.on button { color: var(--fg); background: var(--sel); }
  .grid { flex: 1; min-width: 0; overflow: auto; padding: 12px 16px; }
  .grid.narrow { max-width: 46%; }
  .crumbs { margin-bottom: 10px; font-weight: 600; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
  .item { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 6px; text-align: left; display: flex; flex-direction: column; gap: 4px; }
  .item.on { border-color: var(--acc); background: var(--sel); }
  .thumb { height: 110px; border-radius: 5px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
  .thumb img { max-width: 100%; max-height: 100%; image-rendering: pixelated; }
  .noimg { font-size: 30px; color: var(--dim); }
  .name { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .meta { display: flex; gap: 6px; align-items: center; font-size: 11px; }
  .detail { flex: 1; min-width: 0; overflow: auto; border-left: 1px solid var(--line); }
</style>
