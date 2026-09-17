<script lang="ts">
  // One MusyX sound group as a compact list: a row per sound effect (and per sample), one shared
  // player. Replaces a page of macro buttons, length labels and an <audio> element per sample.
  import { urls, hex, type AudioStream, type SfxInfo, type GroupInfo } from './api'

  let { entry, audio, sfx, group }: { entry: number; audio: AudioStream[]; sfx: SfxInfo[]; group: GroupInfo | null } = $props()

  // a row that can be played: a sound effect (through its first sample) or a bare sample
  interface Row { key: string; name: string; note: string; sample: number | null; stereo: boolean; seconds: number; rate: number }
  // a long sample directly followed by one of the same length and rate is the left + right of one recording
  const pairs = (n: number) => { const s = audio[n], t = audio[n + 1]; return !!(s && t && s.kind === 'musyx' && s.seconds >= 3 && t.seconds === s.seconds && t.rate === s.rate) }
  const sfxRows = $derived<Row[]>(sfx.map(f => {
    const n = f.streams.length ? f.streams[0] : null
    return { key: 'f' + f.id, name: 'sfx ' + hex(f.id, 4), sample: n, stereo: false, seconds: n !== null ? audio[n]?.seconds ?? 0 : 0, rate: n !== null ? audio[n]?.rate ?? 0 : 0,
             note: `macro ${hex(f.macro, 4)}` + (n === null ? ' · plays through a layer, no direct sample' : ` · sample ${f.streams.map(x => x + 1).join(', ')}`) }
  }))
  const sampleRows = $derived<Row[]>(audio.flatMap((s, n) => n > 0 && pairs(n - 1) ? [] : [{
    key: 's' + n, name: s.kind === 'musyx' ? (pairs(n) ? `samples ${n + 1} + ${n + 2}` : `sample ${n + 1}`) : `stream ${n + 1}`, sample: n, stereo: pairs(n), seconds: s.seconds, rate: s.rate,
    note: [s.label, pairs(n) ? 'left + right pair' : s.channels === 2 ? 'stereo' : '', s.loop ? 'loops' : ''].filter(Boolean).join(' · ') }]))
  const used = $derived(new Set(sfx.flatMap(f => f.streams)))
  const unused = $derived(sfx.length ? sampleRows.filter(r => r.sample !== null && !used.has(r.sample) && !(r.stereo && used.has(r.sample + 1))).length : 0)

  let view = $state<'sfx' | 'samples'>('sfx')
  $effect(() => { entry; view = sfx.length ? 'sfx' : 'samples'; now = null; q = '' })
  let q = $state('')
  const rows = $derived((view === 'sfx' ? sfxRows : sampleRows).filter(r => !q || (r.name + ' ' + r.note).toLowerCase().includes(q.toLowerCase())))

  let now = $state<Row | null>(null)
  let player: HTMLAudioElement | undefined = $state()
  const src = (r: Row) => r.stereo ? urls.audioStereo(entry, r.sample!) : urls.audio(entry, r.sample!)
  function play(r: Row) {
    if (r.sample === null) return
    if (now?.key === r.key && player && !player.paused) { player.pause(); return }
    now = r
    queueMicrotask(() => { if (player) { player.src = src(r); player.load(); player.play().catch(() => {}) } })
  }
  function step(d: number) {
    const ok = rows.filter(r => r.sample !== null)
    if (!ok.length) return
    const i = now ? ok.findIndex(r => r.key === now!.key) : -1
    play(ok[(i + d + ok.length) % ok.length])
  }
  let paused = $state(true)
  const secs = (s: number) => s >= 60 ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}` : s.toFixed(s < 10 ? 2 : 1) + ' s'
</script>

<div class="head">
  {#if sfx.length}
    <div class="seg">
      <button class:on={view === 'sfx'} onclick={() => (view = 'sfx')}>Sound effects <span class="dim">{sfx.length}</span></button>
      <button class:on={view === 'samples'} onclick={() => (view = 'samples')} title={unused ? `${unused} of them are played by no sound effect` : ''}>Samples <span class="dim">{sampleRows.length}</span></button>
    </div>
  {/if}
  <input placeholder="filter…" bind:value={q} style="width:160px">
  {#if group}<span class="dim small">MusyX {group.kind} group {group.id}</span>{/if}
  <span style="flex:1"></span>
  {#if group}<a class="small" href={urls.soundfont(entry)} title="Every sample of the group as a SoundFont 2 bank, playable in any sampler">.sf2</a>{/if}
</div>

<div class="player" class:idle={!now}>
  <button onclick={() => step(-1)} title="previous">⏮</button>
  <button onclick={() => step(1)} title="next">⏭</button>
  <span class="what">{#if now}<b>{now.name}</b> <span class="dim small">{now.note}</span>{:else}<span class="dim">click a row to play it</span>{/if}</span>
  <audio controls bind:this={player} bind:paused></audio>
</div>

<table>
  <thead><tr><th style="width:34px"></th><th>{view === 'sfx' ? 'sound effect' : 'sample'}</th><th>details</th><th class="num">length</th><th class="num">rate</th><th></th></tr></thead>
  <tbody>
    {#each rows as r (r.key)}
      <tr class:on={now?.key === r.key} class:off={r.sample === null} onclick={() => play(r)}>
        <td><span class="pl">{now?.key === r.key && !paused ? '⏸' : '▶'}</span></td>
        <td class="mono">{r.name}</td>
        <td class="dim small">{r.note}</td>
        <td class="num">{r.sample !== null ? secs(r.seconds) : ''}</td>
        <td class="num dim">{r.sample !== null ? (r.rate / 1000).toFixed(1) + ' kHz' : ''}</td>
        <td class="num">{#if r.sample !== null}<a class="small" href={r.stereo ? urls.audioStereo(entry, r.sample, true) : urls.audioDownload(entry, r.sample)} onclick={e => e.stopPropagation()}>WAV</a>{/if}</td>
      </tr>
    {/each}
  </tbody>
</table>
{#if !rows.length}<div class="dim" style="padding:12px">nothing matches</div>{/if}

<style>
  .head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
  .seg { display: inline-flex; }
  .seg button { border-radius: 0; margin-left: -1px; }
  .seg button:first-child { border-radius: 6px 0 0 6px; margin-left: 0; }
  .seg button:last-child { border-radius: 0 6px 6px 0; }
  .seg button.on { background: var(--sel); border-color: var(--acc); position: relative; }
  .player { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: 8px; padding: 6px 8px; margin-bottom: 8px; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
  .player.idle audio { opacity: .45; }
  .player .what { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .player audio { height: 30px; width: 320px; max-width: 45%; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-weight: 500; color: var(--dim); font-size: 12px; padding: 4px 8px; border-bottom: 1px solid var(--line); }
  td { padding: 3px 8px; border-bottom: 1px solid color-mix(in srgb, var(--line) 50%, transparent); }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: var(--panel2); }
  tbody tr.on { background: var(--sel); }
  tbody tr.off { cursor: default; opacity: .55; }
  .pl { color: var(--acc); font-size: 12px; }
  tr.off .pl { visibility: hidden; }
  .num { text-align: right; white-space: nowrap; }
  .mono { font-family: ui-monospace, Consolas, monospace; font-size: 12px; white-space: nowrap; }
  .small { font-size: 12px; }
</style>
