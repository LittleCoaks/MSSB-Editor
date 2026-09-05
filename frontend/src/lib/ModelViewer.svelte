<script lang="ts">
  import { onMount } from 'svelte'
  import * as THREE from 'three'
  import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
  import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
  import { urls, type ModelInfo } from './api'

  let { entry, models }: { entry: number; models: ModelInfo[] } = $props()
  let canvas: HTMLCanvasElement
  let section = $state(models[0]?.section ?? 0)
  let wire = $state(false)
  let msg = $state('')
  let renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera, controls: OrbitControls
  let root: THREE.Object3D | null = null
  let grid: THREE.GridHelper
  let alive = true

  onMount(() => {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
    renderer.setPixelRatio(devicePixelRatio)
    scene = new THREE.Scene()
    scene.background = new THREE.Color(0x101216)
    camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100000)
    controls = new OrbitControls(camera, canvas)
    scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.1))
    const dir = new THREE.DirectionalLight(0xffffff, 0.6); dir.position.set(1, 2, 1.5); scene.add(dir)
    grid = new THREE.GridHelper(1000, 20, 0x334455, 0x223344); scene.add(grid)
    const tick = () => {
      if (!alive) return
      const w = canvas.clientWidth, h = canvas.clientHeight
      if (w && h && (canvas.width !== w * devicePixelRatio || canvas.height !== h * devicePixelRatio)) { renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix() }
      controls.update(); renderer.render(scene, camera); requestAnimationFrame(tick)
    }
    tick()
    return () => { alive = false; renderer.dispose() }
  })

  $effect(() => { const s = section, e = entry; if (renderer) load(e, s) })
  $effect(() => { const w = wire; root?.traverse(o => { if ((o as THREE.Mesh).isMesh) ((o as THREE.Mesh).material as THREE.MeshStandardMaterial).wireframe = w }) })

  function load(e: number, s: number) {
    msg = 'loading…'
    new GLTFLoader().load(urls.glb(e, s), g => {
      if (root) scene.remove(root)
      root = g.scene; scene.add(root)
      let tris = 0
      root.traverse(o => { const m = o as THREE.Mesh; if (m.isMesh) { tris += m.geometry.index ? m.geometry.index.count / 3 : 0; (m.material as THREE.Material).side = THREE.DoubleSide; (m.material as THREE.MeshStandardMaterial).wireframe = wire } })
      reset()
      msg = `${Math.round(tris).toLocaleString()} triangles · drag to orbit, wheel to zoom, right-drag to pan`
    }, undefined, err => (msg = 'could not load model: ' + err))
  }
  function reset() {
    if (!root) return
    const box = new THREE.Box3().setFromObject(root), size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3())
    const r = Math.max(size.x, size.y, size.z, 1)
    grid.position.y = box.min.y; grid.scale.setScalar(r / 500)
    camera.position.set(c.x + r * 0.9, c.y + r * 0.6, c.z + r * 1.2); camera.near = r / 1000; camera.far = r * 50; camera.updateProjectionMatrix()
    controls.target.copy(c); controls.update()
  }
</script>

<div class="bar">
  {#if models.length > 1}
    <select bind:value={section}>
      {#each models as m}<option value={m.section}>{m.meshes.join(', ')} ({m.triangles.toLocaleString()} tris)</option>{/each}
    </select>
  {/if}
  <label><input type="checkbox" bind:checked={wire}> wireframe</label>
  <button onclick={reset}>Reset view</button>
  <a class="btn" href={urls.glb(entry, section)}>Download .glb</a>
  <a class="btn" href={urls.obj(entry, section)}>Download .obj</a>
  <span class="dim">{msg}</span>
</div>
<canvas bind:this={canvas}></canvas>

<style>
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
  canvas { width: 100%; height: 65vh; min-height: 320px; display: block; border: 1px solid var(--line); border-radius: 6px; background: #101216; }
</style>
