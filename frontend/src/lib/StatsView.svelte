<script lang="ts">
  // The character stat table and the preset line-ups.
  import { api, type RosterData, type StatRow } from './api'

  let { entry }: { entry: number } = $props()
  let d = $state<RosterData | null>(null)
  let view = $state('stats')
  let sel = $state<number | null>(null)
  $effect(() => {
    const cur = entry
    d = null; sel = null
    api.rosterData(cur).then(r => { if (cur === entry) d = r })
  })
  const COLS: [string, string, string][] = [
    ['class_name', 'class', ''], ['captain', 'capt.', '1 = a team captain'],
    ['batting_bar', 'bat', 'stat bar shown in the menus (0-10)'], ['pitching_bar', 'pitch', 'stat bar shown in the menus'],
    ['running_bar', 'run', 'stat bar shown in the menus'], ['fielding_bar', 'field', 'stat bar shown in the menus'],
    ['slap_contact', 'slap ct', 'slap hit contact size'], ['charge_contact', 'chg ct', 'charge hit contact size'],
    ['slap_power', 'slap pw', 'slap hit power'], ['charge_power', 'chg pw', 'charge hit power'], ['bunting_contact', 'bunt', 'bunting contact size'],
    ['trajectory_push_pull', 'push', 'hit trajectory: push / pull'], ['trajectory_high_low', 'high', 'hit trajectory: high / low'],
    ['speed', 'speed', 'running speed'], ['throwing_arm', 'arm', 'throwing arm strength'], ['weight', 'wt', ''],
    ['curve_ball_speed', 'curve spd', ''], ['fast_ball_speed', 'fast spd', ''], ['cursed_ball', 'cursed', 'cursed ball'], ['curve', 'curve', ''], ['curve_control', 'ctrl', 'curve control'],
    ['batting_stance', 'bats', '0 right, 1 left'], ['fielding_arm', 'throws', '0 right, 1 left'],
    ['captain_star_hit_pitch', 'capt★', 'captain star hit / pitch'], ['star_swing', '★swing', 'non-captain star swing'], ['star_pitch', '★pitch', 'non-captain star pitch'],
  ]
  const chem = (v: number) => v >= 90 ? 'good' : v <= 20 ? 'bad' : ''   // 90+ positive chemistry, 20 and under anti-chemistry
</script>

{#if !d}
  <div class="dim">loading…</div>
{:else}
  <div class="row" style="margin-bottom:8px">
    <button class:on={view === 'stats'} onclick={() => (view = 'stats')}>Stats ({d.stats.length})</button>
    <button class:on={view === 'chem'} onclick={() => (view = 'chem')}>Chemistry</button>
    <button class:on={view === 'lineups'} onclick={() => (view = 'lineups')}>Line-ups ({d.lineups.length})</button>
  </div>
  {#if view === 'stats'}
    <p class="dim" style="margin:0 0 8px">One 160-byte row per character in roster order, the layout of the decomp's CharacterStats (game.rel copies nine of these into the in-play roster). Numbers are the raw bytes; the four "bar" columns are what the menus draw. Click a row for its fielding abilities.</p>
    <div style="overflow:auto">
      <table class="stats">
        <thead><tr><th>#</th><th style="text-align:left">character</th>{#each COLS as [, h, tip]}<th title={tip}>{h}</th>{/each}</tr></thead>
        <tbody>
          {#each d.stats as p}
            <tr class:sel={sel === p.char_id} onclick={() => (sel = sel === p.char_id ? null : p.char_id)}>
              <td class="dim">{p.char_id}</td><td style="text-align:left;white-space:nowrap">{p.name}</td>
              {#each COLS as [k]}<td>{p[k]}</td>{/each}
            </tr>
            {#if sel === p.char_id}
              <tr class="detail"><td colspan={COLS.length + 2}>
                <b>{p.name}</b> · fielding abilities: {p.fielding_abilities.length ? p.fielding_abilities.join(', ') : 'none'} (flags 0x{p.fielding_flags.toString(16)})
                {#if p.spare.replace(/0/g, '')} · spare bytes: <code>{p.spare}</code>{/if}
              </td></tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
  {:else if view === 'chem'}
    <p class="dim" style="margin:0 0 8px">Each row's 54 chemistry bytes, one per teammate in roster order (row = the character, column = the teammate). 90 and up is positive chemistry (green), 20 and down is anti-chemistry (red).</p>
    <div style="overflow:auto">
      <table class="chem">
        <thead><tr><th></th>{#each d.stats as q}<th title={q.name}><div class="rot">{q.name}</div></th>{/each}</tr></thead>
        <tbody>
          {#each d.stats as p}
            <tr><th style="text-align:left;white-space:nowrap">{p.name}</th>{#each p.chemistry as v, i}<td class={chem(v)} title="{p.name} with {d.names[i]}">{v}</td>{/each}</tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <p class="dim" style="margin:0 0 8px">18-byte records after the stat rows: up to nine character ids, then nine bytes that are always 0x0A. 528 slots, of which these are filled; they come in groups of four per captain (the full nine, shorter squads, the captain alone) in the challenge-mode captain order. Which menu reads them has not been traced in the code.</p>
    <table class="lineups">
      <thead><tr><th>#</th><th style="text-align:left">members</th><th>tail</th></tr></thead>
      <tbody>
        {#each d.lineups as l}
          <tr><td class="dim">{l.n}</td><td style="text-align:left">{l.members.map(m => d!.names[m] ?? m).join(', ')}{#if !l.members.length}<span class="dim">(empty)</span>{/if}</td><td class="dim"><code>{l.tail}</code></td></tr>
        {/each}
      </tbody>
    </table>
  {/if}
{/if}

<style>
  table { border-collapse: collapse; font-size: 12px; }
  th, td { padding: 2px 5px; border-bottom: 1px solid var(--line); text-align: right; font-variant-numeric: tabular-nums; }
  th { color: var(--dim); font-weight: normal; white-space: nowrap; }
  .stats tbody tr { cursor: pointer; }
  .stats tbody tr:hover td { background: var(--panel); }
  .stats tr.sel td { background: var(--panel); }
  .stats tr.detail td { text-align: left; }
  .chem td { font-size: 10px; padding: 1px 3px; }
  .chem td.good { color: #7ccf7c; }
  .chem td.bad { color: #e07070; }
  .rot { writing-mode: vertical-rl; transform: rotate(180deg); font-size: 10px; white-space: nowrap; }
  button.on { border-color: var(--acc); color: var(--fg); }
</style>
