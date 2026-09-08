"""Application state shared by all routes: the Store for the selected game,
background jobs, the write lock and cached views."""
from __future__ import annotations

import threading

from .. import catalog
from ..store import Store
from .jobs import Jobs


class AppContext:
    def __init__(self):
        self.store: Store | None = None
        self.store_error = ""
        self.jobs = Jobs()
        self.write_lock = threading.Lock()  # every mutation of the game runs under this
        self._catalog: dict | None = None
        self._catalog_lock = threading.Lock()

    def load_store(self) -> None:
        """(Re)open the configured game. Called at start and after the game or its files change."""
        self.invalidate()
        try:
            self.store = Store()
            self.store_error = ""
        except Exception as ex:
            self.store = None
            self.store_error = str(ex)

    def invalidate(self) -> None:
        with self._catalog_lock:
            self._catalog = None

    def catalog(self) -> dict:
        with self._catalog_lock:
            if self._catalog is None and self.store:
                self._catalog = catalog.build_catalog(self.store.entries)
            return self._catalog or {"categories": [], "names": {}}

    def require_store(self) -> Store:
        if self.store is None:
            raise NoGame(self.store_error or "no game selected")
        return self.store


class NoGame(Exception):
    pass
