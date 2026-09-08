import { api, friendlyName, setCatalogNames, type Catalog, type EntrySummary, type GameInfo, type UpdateInfo } from './api'

export type Page = 'files' | 'characters' | 'stadiums' | 'music' | 'game'

class AppState {
  page = $state<Page>('files')
  game = $state<GameInfo | null>(null)
  entries = $state<Map<number, EntrySummary>>(new Map())
  archiveSize = $state(0)   // bytes in ZZZZ.dat, for the archive map
  catalog = $state<Catalog | null>(null)
  loading = $state(false)
  error = $state('')
  // browse selection; no category means "everything", which is how Browse opens
  category = $state<string>('')
  group = $state<string>('')
  selected = $state<number | null>(null)
  search = $state('')
  modified = $state<number[]>([])
  update = $state<UpdateInfo | null>(null)   // version and the last release check
  updateDismissed = $state(false)


  async checkUpdates(force = false) {
    try {
      const info = await api.update(false)
      this.update = info
      if (info.check_updates || force) this.update = await api.update(true, force)
    } catch { /* offline or no server: the banner just stays away */ }
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
        if (this.category && !cat.categories.some(c => c.id === this.category)) this.category = ''
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
  open(id: number) { this.selected = id; this.page = 'files' }
}

export const app = new AppState()
