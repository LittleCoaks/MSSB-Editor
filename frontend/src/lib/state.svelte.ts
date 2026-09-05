import { api, setCatalogNames, type Catalog, type EntrySummary, type GameInfo } from './api'

export type Page = 'home' | 'browse' | 'music' | 'game'

class AppState {
  page = $state<Page>('home')
  game = $state<GameInfo | null>(null)
  entries = $state<Map<number, EntrySummary>>(new Map())
  catalog = $state<Catalog | null>(null)
  loading = $state(false)
  error = $state('')
  // browse selection
  category = $state<string>('characters')
  group = $state<string>('')
  selected = $state<number | null>(null)
  search = $state('')

  async refresh() {
    this.loading = true
    this.error = ''
    try {
      this.game = await api.game()
      if (this.game.ok) {
        const [idx, cat] = await Promise.all([api.index(), api.catalog()])
        this.entries = new Map(idx.entries.map(e => [e.id, e]))
        this.catalog = cat
        setCatalogNames(cat.names ?? {})
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

  go(page: Page) { this.page = page; location.hash = page }
  open(id: number) { this.selected = id; this.page = 'browse' }
}

export const app = new AppState()
