import { api, friendlyName, setCatalogNames, type Catalog, type EntrySummary, type GameInfo } from './api'

export type Page = 'browse' | 'files' | 'characters' | 'stadiums' | 'music' | 'game'

class AppState {
  page = $state<Page>('browse')
  game = $state<GameInfo | null>(null)
  entries = $state<Map<number, EntrySummary>>(new Map())
  archiveSize = $state(0)   // bytes in ZZZZ.dat, for the archive map
  catalog = $state<Catalog | null>(null)
  loading = $state(false)
  error = $state('')
  // browse selection
  category = $state<string>('characters')
  group = $state<string>('')
  selected = $state<number | null>(null)
  search = $state('')
  modified = $state<number[]>([])
  thumbs = $state<{ running: boolean; done: number; total: number }>({ running: false, done: 0, total: 0 })
  thumbGen = $state(0)  // bumps when the thumbnail build finishes so cards reload their images

  async watchThumbs() {
    for (;;) {
      try { this.thumbs = await api.thumbs() } catch { return }
      if (!this.thumbs.running) { this.thumbGen++; return }
      await new Promise(r => setTimeout(r, 1500))
    }
  }

  async refresh() {
    this.loading = true
    this.error = ''
    try {
      this.game = await api.game()
      if (this.game.ok) {
        const [idx, cat] = await Promise.all([api.index(), api.catalog()])
        this.entries = new Map(idx.entries.map(e => [e.id, e]))
        this.archiveSize = idx.archive_size
        this.catalog = cat
        setCatalogNames(cat.names ?? {})
        this.modified = (await api.modified()).ids
        this.watchThumbs()
        if (!cat.categories.some(c => c.id === this.category)) this.category = cat.categories[0]?.id ?? ''
      } else {
        this.entries = new Map()
        this.catalog = null
        this.page = 'game'
      }
    } catch (e: any) {
      this.error = String(e.message ?? e)
    } finally {
      this.loading = false
    }
  }

  nameOf(e: EntrySummary): string {
    const n = this.catalog?.names?.[String(e.id)]
    return n ?? friendlyName(e)
  }

  go(page: Page) { this.page = page; location.hash = page }
  open(id: number) { this.selected = id; this.page = 'browse' }
}

export const app = new AppState()
