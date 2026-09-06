<script lang="ts">
  import { onMount } from 'svelte'
  import * as THREE from 'three'
  import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
  import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
  import { urls, type BankInfo, type ModelInfo } from './api'

  let { entry, models, banks = [], parts = [], variants = [], bank = $bindable(''), height = '65vh', pose = undefined, whole = false }: { entry: number; models: Pick<ModelInfo, 'section' | 'meshes' | 'triangles'>[]; banks?: BankInfo[]; parts?: string[]; variants?: { slot: number; name: string; entry: number }[]; bank?: string; height?: string; pose?: number; whole?: boolean } = $props()
  let part = $state('')          // '', 'hands' or 'gloves'
  let variant = $state<number | undefined>(undefined)  // colour variant slot
  let canvas: HTMLCanvasElement
  let section = $state(models[0]?.section ?? 0)
  let wire = $state(false)
  // `bank`: animation bank key, '' = static export (bindable so a page can drive it)
  let clips = $state<THREE.AnimationClip[]>([])
  let clip = $state('')
  let playing = $state(true)
  let speed = $state(1)
  let frame = $state(0)
  let msg = $state('')
  let renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera, controls: OrbitControls
  let root: THREE.Object3D | null = null
  let mixer: THREE.AnimationMixer | null = null
  let action: THREE.AnimationAction | null = null
  let grid: THREE.GridHelper
  let alive = true
  const clock = new THREE.Clock()

  onMount(() => {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
    renderer.setPixelRatio(devicePixelRatio)
    scene = new THREE.Scene()
    scene.background = new THREE.Color(0x101216)
    camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100000)
    controls = new OrbitControls(camera, canvas)
    controls.zoomToCursor = true
    controls.zoomSpeed = 1.4
    scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.1))
    const dir = new THREE.DirectionalLight(0xffffff, 0.6); dir.position.set(1, 2, 1.5); scene.add(dir)
    grid = new THREE.GridHelper(1000, 20, 0x334455, 0x223344); scene.add(grid)
    const tick = () => {
      if (!alive) return
      const w = canvas.clientWidth, h = canvas.clientHeight
      if (w && h && (canvas.width !== w * devicePixelRatio || canvas.height !== h * devicePixelRatio)) { renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix() }
      const dt = clock.getDelta()
      if (mixer && playing) { mixer.update(dt * speed); if (action) frame = Math.round(action.time * 60) }
      controls.update(); renderer.render(scene, camera); requestAnimationFrame(tick)
    }
    tick()
    return () => { alive = false; renderer.dispose() }
  })

  $effect(() => { const s = section, e = entry, b = bank, p = part, v = variant, k = pose; if (renderer) load(e, s, b, p, v, k) })
  $effect(() => { const w = wire; root?.traverse(o => { if ((o as THREE.Mesh).isMesh) ((o as THREE.Mesh).material as THREE.MeshStandardMaterial).wireframe = w }) })
  $effect(() => { const c = clip; if (mixer) play(c) })
  let lastEntry = entry
  $effect(() => { if (entry !== lastEntry) { lastEntry = entry; bank = ''; part = ''; variant = undefined } })

  function load(e: number, s: number, b: string, p: string, v?: number, k?: number) {
    msg = 'loading…'
    new GLTFLoader().load(whole ? urls.scene(e) : urls.glb(e, s, b || undefined, p || undefined, v, k), g => {
      if (root) scene.remove(root)
      root = g.scene; scene.add(root)
      let tris = 0
      root.traverse(o => { const m = o as THREE.Mesh; if (m.isMesh) { tris += m.geometry.index ? m.geometry.index.count / 3 : 0; const mat = m.material as THREE.MeshStandardMaterial; mat.side = isSky(m) ? THREE.BackSide : THREE.DoubleSide; if (isGlare(m)) { m.visible = false }  /* the sun-glare billboard is a screen effect, not scenery */ mat.wireframe = wire; m.frustumCulled = false } })
      mixer = g.animations.length ? new THREE.AnimationMixer(root) : null
      action = null
      clips = g.animations
      clip = g.animations[0]?.name ?? ''
      if (mixer) play(clip)
      reset()
      msg = `${Math.round(tris).toLocaleString()} triangles` + (g.animations.length ? ` · ${g.animations.length} animations` : '') + ' · drag to orbit, wheel to zoom, right-drag to pan'
    }, undefined, err => (msg = 'could not load model: ' + err))
  }
  // a stadium's sky dome encloses the park: draw it inside-out so the orbit camera looks through it
  const isSky = (m: THREE.Object3D) => /sky|cloud|enkei/i.test(m.name) || /sky|cloud/i.test(m.parent?.name ?? '')
  const isGlare = (m: THREE.Object3D) => /glare/.test(m.name) || /glare/.test(m.parent?.name ?? '')
  function play(name: string) {
    if (!mixer) return
    const c = clips.find(x => x.name === name)
    if (!c) return
    mixer.stopAllAction()
    action = mixer.clipAction(c); action.reset().play()
    frame = 0
  }
  function seek(f: number) { if (action) { action.paused = false; action.time = f / 60; playing = false; action.paused = true; frame = f } }
  function reset() {
    if (!root) return
    if (mixer) mixer.update(0)
    root.updateMatrixWorld(true)
    // bounds from the meshes in their current pose plus every bone position, so a rigged
    // character is framed as a whole even when the body is skinned
    const box = new THREE.Box3()
    root.traverse(o => {
      const m = o as THREE.Mesh
      if (m.isMesh && !(m as THREE.SkinnedMesh).isSkinnedMesh && !isSky(m)) box.expandByObject(m)
      if (o.name.startsWith('bone')) box.expandByPoint(o.getWorldPosition(new THREE.Vector3()))
    })
    if (box.isEmpty()) box.setFromObject(root)
    const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3())
    const r = Math.max(size.x, size.y, size.z, 1)
    grid.position.y = box.min.y; grid.scale.setScalar(r / 500)
    camera.position.set(c.x + r * 1.1, c.y + r * 0.35, c.z + r * 1.4); camera.near = r / 5000; camera.far = r * 50; camera.updateProjectionMatrix()
    controls.minDistance = r / 500; controls.maxDistance = r * 20
    controls.target.copy(c); controls.update()
  }
  const duration = $derived(clips.find(x => x.name === clip)?.duration ?? 0)
  $effect(() => { if (action) action.paused = !playing })
</script>

<div class="tools">
  {#if models.length > 1 && !whole}
    <select bind:value={section}>
      {#each models as m}<option value={m.section}>{m.meshes.join(', ')} ({m.triangles.toLocaleString()} tris)</option>{/each}
    </select>
  {/if}
  {#if banks.length}
    <select bind:value={bank} title="Animation bank">
      <option value="">no animation</option>
      {#each banks as b}<option value={b.key}>{b.label}{b.sequences ? ` · ${b.sequences} sequences` : ''}</option>{/each}
    </select>
  {/if}
  {#if variants.length}
    <select bind:value={variant} title="Colour variant (same model, another texture set)">
      <option value={undefined}>own colours</option>
      {#each variants as v}<option value={v.slot}>{v.name}</option>{/each}
    </select>
  {/if}
  {#if parts.length}
    <select bind:value={part} title="Attached parts">
      <option value="">body only</option>
      {#if parts.some(p => p.endsWith('hand'))}<option value="hands">with hands</option>{/if}
      {#if parts.some(p => p.endsWith('glove'))}<option value="gloves">with gloves</option>{/if}
      {#if parts.some(p => p.endsWith('bat'))}<option value="bat">with bat</option>{/if}
    </select>
  {/if}
  <label><input type="checkbox" bind:checked={wire}> wireframe</label>
  <button onclick={reset}>Reset view</button>
  {#if whole}<a class="btn" href={urls.scene(entry)}>Download .glb (whole scene)</a>{:else}<a class="btn" href={urls.glb(entry, section, bank || undefined, part || undefined, variant, pose)}>Download .glb</a>
  <a class="btn" href={urls.obj(entry, section, pose)}>Download .obj</a>{/if}
  <span class="dim">{msg}</span>
</div>
{#if clips.length}
  <div class="tools anim">
    <select bind:value={clip}>
      {#each clips as c}<option value={c.name}>{c.name} ({Math.round(c.duration * 60)} frames)</option>{/each}
    </select>
    <button onclick={() => (playing = !playing)}>{playing ? '⏸ pause' : '▶ play'}</button>
    <input type="range" min="0" max={Math.max(1, Math.round(duration * 60))} value={frame} oninput={e => seek(+(e.target as HTMLInputElement).value)} style="flex:1;min-width:120px">
    <span class="dim mono">frame {frame} / {Math.round(duration * 60)}</span>
    <select bind:value={speed} title="speed">
      <option value={0.25}>¼×</option><option value={0.5}>½×</option><option value={1}>1×</option><option value={2}>2×</option>
    </select>
  </div>
{/if}
<canvas bind:this={canvas} style="height:{height}"></canvas>

<style>
  .tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }  /* not .bar: app.css uses that for progress bars */
  .mono { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
  canvas { width: 100%; height: 65vh; min-height: 320px; display: block; border: 1px solid var(--line); border-radius: 6px; background: #101216; }
</style>
