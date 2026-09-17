<script lang="ts">
  // Every sound-effect group of the game in one place: the groups down the side, one group's
  // sounds as a compact list with a single player (SoundList).
  import { api, type EntryDetail, type SoundGroup } from './api'
  import { app } from './state.svelte'
  import SoundList from './SoundList.svelte'

  let groups = $state<SoundGroup[]>([])
  let current = $state<number | null>(null)
  let d = $state<EntryDetail | null>(null)
  let err = $state('')
  let q = $state('')

  async function load() {
    try { groups = (await api.sounds()).groups; err = '' } catch (e: any) { err = e.message; return }
    const h = location.hash.match(/^#music\/sounds\/(\d+)/)
    const want = h ? +h[1] : current
    pick(groups.some(g => g.entry === want) ? want! : groups.find(g => !g.character)?.entry ?? groups[0]?.entry ?? null)
  }
  $effect(() => { app.game; load() })
  async function pick(id: number | null) {
    if (id === null) return
    current = id; d = null
    location.hash = 'music/sounds/' + id
    try { const x = await api.entry(id); if (current === id) d = x } catch (e: any) { err = e.message }
  }
  const shown = $derived(groups.filter(g => !q || g.name.toLowerCase().includes(q.toLowerCase())))
  const general = $derived(shown.filter(g => !g.character && !g.stadium))
  const parks = $derived(shown.filter(g => g.stadium))
  const voices = $derived(shown.filter(g => g.character).sort((a, b) => a.name.localeCompare(b.name)))
  const cur = $derived(groups.find(g => g.entry === current))
</script>

<div class="page">
  <aside>
    <input placeholder="find a group…" bind:value={q} style="width:100%;margin-bottom:8px">
    {#each [['Game sounds', general], ['Stadiums', parks], ['Character voices', voices]] as [title, list]}
      {#if (list as SoundGroup[]).length}
        <div class="lbl">{title}</div>
        <ul>
          {#each list as SoundGroup[] as g (g.entry)}
            <li class:on={g.entry === current}><button onclick={() => pick(g.entry)}>
              <span class="nm">{g.name}</span><span class="dim sub">{g.sfx ? `${g.sfx} sounds` : `${g.samples} samples`}</span>
            </button></li>
          {/each}
        </ul>
      {/if}
    {/each}
  </aside>
  <section>
    {#if err}<div class="card warn">{err}</div>
    {:else if !d || !cur}<div class="dim">loading…</div>
    {:else}
      <header>
        <h2>{cur.name}</h2>
        <span class="dim">{cur.sfx} sound effects · {cur.samples} samples · {cur.seconds} s of audio · <a href="#entry/{cur.entry}" onclick={() => app.open(cur.entry)}>open in Browse assets</a></span>
      </header>
      <SoundList entry={d.id} audio={d.audio} sfx={d.sfx} group={d.group} />
    {/if}
  </section>
</div>

<style>
  .page { flex: 1; display: flex; min-height: 0; }
  aside { width: 240px; flex: none; overflow: auto; border-right: 1px solid var(--line); padding: 10px; background: var(--panel); }
  aside ul { list-style: none; margin: 0 0 10px; padding: 0; }
  aside li button { width: 100%; display: flex; justify-content: space-between; align-items: baseline; gap: 8px; background: none; border: none; padding: 5px 8px; border-radius: 6px; text-align: left; color: var(--fg); }
  aside li button:hover { background: var(--panel2); }
  aside li.on button { background: var(--sel); }
  .lbl { color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: .05em; margin: 6px 8px 4px; }
  .nm { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sub { font-size: 11px; white-space: nowrap; }
  section { flex: 1; min-width: 0; overflow: auto; padding: 16px 20px; }
  header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
  h2 { margin: 0; }
</style>
