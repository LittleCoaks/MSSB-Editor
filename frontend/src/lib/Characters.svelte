<script lang="ts">
  // Character slots: make one slot play as another character, and undo it.
  import { api, type SlotInfo } from './api'
  import { app } from './state.svelte'

  let slots = $state<SlotInfo[]>([])
  let editable = $state(false)
  let source = $state(2)
  let target = $state(1)
  let copy = $state(true)
  let busy = $state(false)
  let msg = $state('')
  let ok = $state(false)

  async function load() {
    try { const r = await api.characters(); slots = r.slots; editable = r.editable } catch (e: any) { msg = e.message }
  }
  $effect(() => { app.game; load() })

  async function clone() {
    busy = true; msg = 'cloning… (copying the character files takes a few seconds)'; ok = false
    try {
      const r = await api.cloneCharacter(source, target, copy)
      const inplace = r.inplace.length ? `, ${r.inplace.length} body/rig entries copied in place` : ''
      msg = `${r.target_name} now plays as ${r.source_name}: ${r.copied} files copied${inplace}, ${r.shared} descriptors shared. Slot ${r.target} appears under ${r.target_name} in Browse, so its textures can be replaced separately.`
      ok = true
      await app.refresh(); await load()
    } catch (e: any) { msg = e.message } finally { busy = false }
  }
  async function restore(slot: number) {
    busy = true; msg = 'restoring…'; ok = false
    try { await api.restoreCharacter(slot); msg = `Slot ${slot} restored.`; ok = true; await app.refresh(); await load() } catch (e: any) { msg = e.message } finally { busy = false }
  }
  const cloned = $derived(slots.filter(s => s.clone_of !== null))
</script>

<div class="page">
  <div class="card" style="max-width:760px">
    <h2 style="margin:0 0 6px">Clone a character</h2>
    <p class="dim" style="margin:0 0 12px">Makes one roster slot play as another character: model, equipment, all 17 animation banks, hands, bats, grips, skeleton and glove bones. Only the game's own tables in <code>main.dol</code> change; no code is patched. The original can always be restored.</p>
    {#if !editable}
      <p class="warn">Editing needs an extracted game with ZZZZ.dat and aaaa.dat. Use <a href="#game" onclick={() => app.go('game')}>Prepare for editing</a> on the Game page.</p>
    {:else}
      <div class="row">
        <label>Play as <select bind:value={source} disabled={busy}>{#each slots as s}<option value={s.slot}>{s.slot} · {s.name}</option>{/each}</select></label>
        <span class="dim">→</span>
        <label>in slot <select bind:value={target} disabled={busy}>{#each slots as s}<option value={s.slot} disabled={s.clone_of !== null}>{s.slot} · {s.name}{s.clone_of !== null ? ' (cloned)' : ''}</option>{/each}</select></label>
        <button class="primary" onclick={clone} disabled={busy || source === target}>Clone</button>
      </div>
      <label class="row" style="margin-top:10px"><input type="checkbox" bind:checked={copy} disabled={busy}> copy the files (about 4 MB appended to ZZZZ.dat) so the clone's textures can be edited without changing the original. Unticked, both slots share one set of files.</label>
    {/if}
    {#if msg}<p class={ok ? 'ok' : busy ? 'dim' : 'warn'} style="margin-top:10px">{msg}</p>{/if}
  </div>

  <div class="card" style="max-width:760px;margin-top:14px">
    <h3 style="margin:0 0 8px">Slots</h3>
    {#if cloned.length === 0}<p class="dim">No slot is cloned. The table below is the stock roster.</p>{/if}
    <table>
      <thead><tr><th>#</th><th>slot</th><th>plays as</th><th></th></tr></thead>
      <tbody>
        {#each slots as s}
          <tr class:mod={s.clone_of !== null}>
            <td class="dim">{s.slot}</td>
            <td>{s.name}</td>
            <td>{#if s.clone_of !== null}<span class="ok">{s.clone_of_name}</span> <span class="dim">({s.copy ? 'copied files' : 'shared files'}{s.inplace ? `, ${s.inplace} in place` : ''})</span>{:else}<span class="dim">itself</span>{/if}</td>
            <td>{#if s.clone_of !== null}<button class="danger" onclick={() => restore(s.slot)} disabled={busy}>Restore</button>{/if}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>

<style>
  .page { padding: 16px; overflow: auto; }
  table { width: 100%; }
  td { padding: 4px 10px; }
  code { font-family: ui-monospace, Consolas, monospace; }
</style>
