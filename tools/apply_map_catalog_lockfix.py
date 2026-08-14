from __future__ import annotations

from pathlib import Path
import textwrap


def replace_method(text: str, start_marker: str, end_marker: str, body: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    block = textwrap.indent(textwrap.dedent(body), "    ")
    return text[:start] + block + text[end:]


def patch_catalog() -> None:
    p = Path("eqquest/map_catalog.py")
    s = p.read_text(encoding="utf-8")
    if "from typing import Callable, Iterable" not in s:
        s = s.replace("from typing import Iterable\n", "from typing import Callable, Iterable\n", 1)

    s = replace_method(
        s,
        "    def _upsert_source(\n",
        "    def index_root(",
        '''\
def _upsert_source(
    self,
    *,
    root: str,
    map_stem: str,
    zone_name: str,
    layer: int,
    path: Path,
    mtime_ns: int,
    size: int,
) -> tuple[int, bool]:
    row = self.db.conn.execute(
        "SELECT * FROM map_sources WHERE path=?", (str(path),)
    ).fetchone()
    unchanged = bool(
        row
        and int(row["mtime_ns"] or 0) == int(mtime_ns)
        and int(row["size"] or 0) == int(size)
        and str(row["zone_name"] or "") == zone_name
        and str(row["root"] or "") == root
    )
    if unchanged and row is not None:
        return int(row["id"]), True

    now = datetime.now().isoformat(timespec="seconds")
    self.db.conn.execute(
        """
        INSERT INTO map_sources(root,map_stem,zone_name,layer,path,mtime_ns,size,indexed_at)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(path) DO UPDATE SET
            root=excluded.root,
            map_stem=excluded.map_stem,
            zone_name=excluded.zone_name,
            layer=excluded.layer,
            mtime_ns=excluded.mtime_ns,
            size=excluded.size,
            indexed_at=excluded.indexed_at
        """,
        (root, map_stem, zone_name, int(layer), str(path), int(mtime_ns), int(size), now),
    )
    source_id = int(
        self.db.conn.execute("SELECT id FROM map_sources WHERE path=?", (str(path),)).fetchone()[0]
    )
    return source_id, False

''',
    )

    # The method signature may already have been modified in a failed local checkout,
    # but main should still contain the original at the time this patcher runs.
    start_marker = "    def index_root(self, root: str | Path) -> MapIndexStats:"
    if start_marker not in s:
        start_marker = "    def index_root(\n"
    s = replace_method(
        s,
        start_marker,
        "    def stats(self, root: str | Path | None = None) -> dict[str, int]:",
        '''\
def index_root(
    self,
    root: str | Path,
    *,
    progress: Callable[[str, int, int, str], None] | None = None,
) -> MapIndexStats:
    """Incrementally index map labels without monopolizing SQLite.

    Map files are parsed before a write transaction begins. Changed files are
    committed one file at a time, and reconciliation writes are chunked so the UI
    connection can continue saving settings, view state, and log-derived state.
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(root_path)
    root_s = str(root_path)
    zone_by_stem = self._zone_map()
    base_maps = discover_base_maps(root_path)
    candidates: list[tuple[str, int, Path, str]] = []
    for base in base_maps:
        map_stem = base.stem
        zone_name = zone_by_stem.get(normalize_map_name(map_stem), "")
        for layer_no in range(4):
            path = root_path / (f"{map_stem}.txt" if layer_no == 0 else f"{map_stem}_{layer_no}.txt")
            if path.exists():
                candidates.append((map_stem, layer_no, path.resolve(), zone_name))

    total_files = len(candidates)
    if progress:
        progress("scan", 0, max(1, total_files), f"Scanning {total_files:,} map files")
    seen_paths: set[str] = set()
    files_indexed = 0
    files_unchanged = 0
    stale_removed = 0

    for index, (map_stem, layer_no, path, zone_name) in enumerate(candidates, start=1):
        seen_paths.add(str(path))
        stat = path.stat()
        existing = self.db.conn.execute(
            "SELECT * FROM map_sources WHERE path=?", (str(path),)
        ).fetchone()
        unchanged = bool(
            existing
            and int(existing["mtime_ns"] or 0) == int(stat.st_mtime_ns)
            and int(existing["size"] or 0) == int(stat.st_size)
            and str(existing["zone_name"] or "") == zone_name
            and str(existing["root"] or "") == root_s
        )
        if unchanged:
            files_unchanged += 1
            if progress:
                progress("index", index, max(1, total_files), f"Checked {path.name}")
            continue

        # File parsing is intentionally outside the SQLite transaction.
        parsed = parse_map_file(path, layer=layer_no)
        labels = []
        for point in parsed.points:
            raw = point.display_text
            clean = self._canonical_text(raw)
            labels.append((
                map_stem, zone_name, layer_no, int(point.source_line),
                raw, clean, normalize_name(clean), float(point.x), float(point.y),
                float(point.z), int(point.r), int(point.g), int(point.b), int(point.size),
            ))

        with self.db.batch():
            source_id, _ = self._upsert_source(
                root=root_s,
                map_stem=map_stem,
                zone_name=zone_name,
                layer=layer_no,
                path=path,
                mtime_ns=stat.st_mtime_ns,
                size=stat.st_size,
            )
            self.db.conn.execute("DELETE FROM map_labels WHERE source_id=?", (source_id,))
            if labels:
                self.db.conn.executemany(
                    """
                    INSERT INTO map_labels(
                        source_id,map_stem,zone_name,layer,source_line,
                        raw_text,clean_text,normalized_text,x,y,z,r,g,b,size
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [(source_id, *row) for row in labels],
                )
            self.db.set_meta("map_links_dirty", "1")
        files_indexed += 1
        if progress:
            progress("index", index, max(1, total_files), f"Indexed {path.name} ({len(labels):,} labels)")

    stale = self.db.conn.execute(
        "SELECT id,path FROM map_sources WHERE root=?", (root_s,)
    ).fetchall()
    with self.db.batch():
        for row in stale:
            if str(row["path"]) not in seen_paths:
                self.db.conn.execute("DELETE FROM map_sources WHERE id=?", (int(row["id"]),))
                stale_removed += 1
        self.db.set_meta("map_catalog_root", root_s)
        if stale_removed:
            self.db.set_meta("map_links_dirty", "1")

    reconciliation = self.reconcile_all(
        force=bool(files_indexed or stale_removed), progress=progress
    )
    label_count = int(self.db.conn.execute(
        "SELECT COUNT(*) FROM map_labels ml JOIN map_sources ms ON ms.id=ml.source_id WHERE ms.root=?",
        (root_s,),
    ).fetchone()[0])
    if progress:
        progress("done", 1, 1, f"Ready: {label_count:,} indexed labels")
    return MapIndexStats(
        base_maps=len(base_maps),
        files_indexed=files_indexed,
        files_unchanged=files_unchanged,
        labels=label_count,
        linked=reconciliation["linked"],
        ambiguous=reconciliation["ambiguous"],
        unresolved=reconciliation["unresolved"],
    )

''',
    )

    s = replace_method(
        s,
        "    def reconcile_all(self, *, force: bool = False) -> dict[str, int]:",
        "    def ensure_reconciled(self) -> None:",
        '''\
def reconcile_all(
    self,
    *,
    force: bool = False,
    progress: Callable[[str, int, int, str], None] | None = None,
    chunk_size: int = 250,
) -> dict[str, int]:
    if not force and self.db.get_meta("map_links_dirty", "1") != "1":
        row = self.db.conn.execute(
            """
            SELECT SUM(link_status='linked'), SUM(link_status='ambiguous'), SUM(link_status='unresolved')
            FROM map_labels
            """
        ).fetchone()
        return {
            "linked": int(row[0] or 0),
            "ambiguous": int(row[1] or 0),
            "unresolved": int(row[2] or 0),
        }

    labels = self.db.conn.execute(
        "SELECT id,normalized_text,zone_name FROM map_labels ORDER BY id"
    ).fetchall()
    total = len(labels)
    if progress:
        progress("reconcile", 0, max(1, total), f"Reconciling {total:,} map labels")
    location_by_zone: dict[str, set[int]] = {}
    linked = ambiguous = unresolved = 0
    pending: list[tuple[int | None, str, str, int]] = []
    chunk_size = max(25, int(chunk_size))

    def flush() -> None:
        if not pending:
            return
        with self.db.batch():
            self.db.conn.executemany(
                "UPDATE map_labels SET linked_entity_id=?,link_status=?,link_reason=? WHERE id=?",
                pending,
            )
        pending.clear()

    for index, label in enumerate(labels, start=1):
        normalized = str(label["normalized_text"] or "")
        zone_name = str(label["zone_name"] or "")
        candidates = list(self._candidate_entities(normalized)) if normalized else []
        chosen = None
        reason = ""
        status = "unresolved"

        if len(candidates) == 1:
            chosen = candidates[0]
            status = "linked"
            reason = "exact cleaned name/alias; unique local entity"
        elif len(candidates) > 1:
            if zone_name:
                key = normalize_name(zone_name)
                if key not in location_by_zone:
                    location_by_zone[key] = {
                        int(r["entity_id"]) for r in self.db.locations_in_zone(zone_name)
                    }
                zone_ids = location_by_zone[key]
                narrowed = [
                    row for row in candidates
                    if self._entity_zone_matches(row, zone_name, zone_ids)
                ]
                if len(narrowed) == 1:
                    chosen = narrowed[0]
                    status = "linked"
                    reason = "exact cleaned name/alias; unique current-zone entity"
                else:
                    status = "ambiguous"
                    reason = f"{len(narrowed) or len(candidates)} exact entity candidates"
            else:
                status = "ambiguous"
                reason = f"{len(candidates)} exact entity candidates"

        entity_id = int(chosen["id"]) if chosen is not None else None
        pending.append((entity_id, status, reason, int(label["id"])))
        if status == "linked":
            linked += 1
        elif status == "ambiguous":
            ambiguous += 1
        else:
            unresolved += 1

        if len(pending) >= chunk_size:
            flush()
            if progress:
                progress("reconcile", index, max(1, total), f"Reconciled {index:,}/{total:,} labels")

    flush()
    with self.db.batch():
        self.db.set_meta("map_links_dirty", "0")
        self.db.set_meta("map_links_last_reconcile", datetime.now().isoformat(timespec="seconds"))
    if progress:
        progress("reconcile", max(1, total), max(1, total), f"Reconciled {total:,} labels")
    return {"linked": linked, "ambiguous": ambiguous, "unresolved": unresolved}

''',
    )

    # Search/hit navigation on the Tk connection must be read-only. The background
    # map-index job owns reconciliation whenever map_links_dirty is set.
    s = s.replace(
        "        self.ensure_reconciled()\n        query = parse_local_query(raw_query)\n",
        "        query = parse_local_query(raw_query)\n",
        1,
    )
    s = s.replace(
        "    def hits_for_entity(self, entity_id: int, *, limit: int = 100) -> list[MapCatalogHit]:\n        self.ensure_reconciled()\n",
        "    def hits_for_entity(self, entity_id: int, *, limit: int = 100) -> list[MapCatalogHit]:\n",
        1,
    )
    p.write_text(s, encoding="utf-8")


def patch_mapview() -> None:
    p = Path("eqquest/mapview.py")
    s = p.read_text(encoding="utf-8")
    s = s.replace(
        '''        self._catalog_index_results: queue.Queue[tuple[str, object]] = queue.Queue()\n        self._catalog_indexing = False\n''',
        '''        self._catalog_index_results: queue.Queue[tuple[str, object]] = queue.Queue()\n        self._catalog_indexing = False\n        self.catalog_progress_var = tk.DoubleVar(value=0.0)\n        self.catalog_progress_text = tk.StringVar(value="Map catalog idle")\n''',
        1,
    )
    s = s.replace(
        '''        ttk.Button(lookup_row, text="Index maps", command=self.index_map_catalog).grid(row=0, column=2, padx=(4, 0))\n''',
        '''        self.index_maps_button = ttk.Button(lookup_row, text="Index maps", command=self.index_map_catalog)\n        self.index_maps_button.grid(row=0, column=2, padx=(4, 0))\n''',
        1,
    )
    s = s.replace(
        '''        ttk.Button(lookup_actions, text="Open Map", command=self._open_lookup_on_map).pack(side="left", padx=(5, 0))\n        ttk.Label(lookup_actions, textvariable=self.lookup_status).pack(side="left", padx=(6, 0))\n''',
        '''        ttk.Button(lookup_actions, text="Open Map", command=self._open_lookup_on_map).pack(side="left", padx=(5, 0))\n        self.catalog_progress = ttk.Progressbar(\n            lookup_actions, variable=self.catalog_progress_var, maximum=1.0, length=135, mode="determinate"\n        )\n        self.catalog_progress.pack(side="right", padx=(6, 0))\n        ttk.Label(lookup_actions, textvariable=self.catalog_progress_text).pack(side="right", padx=(6, 0))\n        ttk.Label(lookup_actions, textvariable=self.lookup_status).pack(side="left", padx=(6, 0))\n''',
        1,
    )

    s = replace_method(
        s,
        "    def index_map_catalog(self) -> None:",
        "    def suggest_root_from_log(self, log_path: str | Path) -> None:",
        '''\
def index_map_catalog(self) -> None:
    root = self.map_root.get().strip()
    if not root or not Path(root).is_dir():
        self.lookup_status.set("Choose a valid map pack before indexing.")
        return
    if self._catalog_indexing:
        return
    self._catalog_indexing = True
    self.index_maps_button.configure(state="disabled")
    self.catalog_progress.configure(maximum=1.0)
    self.catalog_progress_var.set(0.0)
    self.catalog_progress_text.set("Starting map index…")
    self.lookup_status.set("Updating local map catalog in background…")
    db_path = self.db.path

    def worker() -> None:
        thread_db = None
        try:
            thread_db = Database(db_path)

            def progress(stage: str, current: int, total: int, detail: str) -> None:
                self._catalog_index_results.put(("progress", (stage, current, total, detail)))

            stats = MapCatalog(thread_db).index_root(root, progress=progress)
            self._catalog_index_results.put(("ok", stats))
        except Exception as exc:
            self._catalog_index_results.put(("error", str(exc)))
        finally:
            if thread_db is not None:
                thread_db.close()

    threading.Thread(target=worker, name="EverQuestieMapCatalog", daemon=True).start()


def _poll_catalog_index_results(self) -> None:
    try:
        while True:
            status, payload = self._catalog_index_results.get_nowait()
            if status == "progress":
                stage, current, total, detail = payload
                total = max(1, int(total))
                current = max(0, min(int(current), total))
                self.catalog_progress.configure(maximum=float(total))
                self.catalog_progress_var.set(float(current))
                label = {
                    "scan": "Scanning",
                    "index": "Indexing",
                    "reconcile": "Linking",
                    "done": "Ready",
                }.get(str(stage), "Working")
                self.catalog_progress_text.set(f"{label} {current:,}/{total:,}")
                self.lookup_status.set(str(detail))
                continue

            self._catalog_indexing = False
            self.index_maps_button.configure(state="normal")
            if status == "ok":
                stats = payload
                self.catalog_progress.configure(maximum=1.0)
                self.catalog_progress_var.set(1.0)
                self.catalog_progress_text.set("Map catalog ready")
                self.lookup_status.set(
                    f"Map catalog: {stats.labels:,} labels | {stats.linked:,} linked | {stats.ambiguous:,} ambiguous"
                )
            else:
                self.catalog_progress.configure(maximum=1.0)
                self.catalog_progress_var.set(0.0)
                self.catalog_progress_text.set("Map catalog failed")
                self.lookup_status.set(f"Map catalog index failed: {payload}")
    except queue.Empty:
        pass
    self.after(150, self._poll_catalog_index_results)

''',
    )
    p.write_text(s, encoding="utf-8")


if __name__ == "__main__":
    patch_catalog()
    patch_mapview()
