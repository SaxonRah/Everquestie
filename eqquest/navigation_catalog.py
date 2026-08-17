from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .map_catalog import MapCatalog
from .provider_zone_travel import ProviderZoneTravelCatalog, ProviderZoneTravelStats
from .zone_catalog import ZoneMapBindingStats, ZoneMapCatalog
from .zone_provider_reconciliation import (
    ProviderZoneReconciliationCatalog,
    ProviderZoneReconciliationStats,
)
from .zone_travel import ZoneTravelBuildStats, ZoneTravelCatalog


NAVIGATION_CATALOG_VERSION = "6"


@dataclass(frozen=True, slots=True)
class NavigationCatalogRefresh:
    refreshed: bool
    map_bindings: ZoneMapBindingStats | None = None
    travel: ZoneTravelBuildStats | None = None
    provider_zones: ProviderZoneReconciliationStats | None = None
    provider_travel: ProviderZoneTravelStats | None = None


def _install_dirty_triggers(db) -> None:
    """Mark builder-owned navigation derivatives stale when their inputs change."""
    db.conn.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_zone_insert
        AFTER INSERT ON entities
        WHEN NEW.kind='zone'
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_zone_update
        AFTER UPDATE OF name,normalized_name,data_json ON entities
        WHEN OLD.kind='zone' OR NEW.kind='zone'
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_zone_delete
        AFTER DELETE ON entities
        WHEN OLD.kind='zone'
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_alias_insert
        AFTER INSERT ON entity_aliases
        WHEN EXISTS(SELECT 1 FROM entities WHERE id=NEW.entity_id AND kind='zone')
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_alias_update
        AFTER UPDATE ON entity_aliases
        WHEN EXISTS(SELECT 1 FROM entities WHERE id=NEW.entity_id AND kind='zone')
          OR EXISTS(SELECT 1 FROM entities WHERE id=OLD.entity_id AND kind='zone')
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_alias_delete
        AFTER DELETE ON entity_aliases
        WHEN EXISTS(SELECT 1 FROM entities WHERE id=OLD.entity_id AND kind='zone')
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_external_insert
        AFTER INSERT ON entity_external_ids
        WHEN NEW.namespace='eqclient:zone'
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_external_update
        AFTER UPDATE ON entity_external_ids
        WHEN OLD.namespace='eqclient:zone' OR NEW.namespace='eqclient:zone'
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_external_delete
        AFTER DELETE ON entity_external_ids
        WHEN OLD.namespace='eqclient:zone'
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_connected_insert
        AFTER INSERT ON entity_relationships
        WHEN NEW.relation='connected_to'
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_connected_update
        AFTER UPDATE OF source_entity_id,target_entity_id,relation,source_page_id,evidence,data_json
        ON entity_relationships
        WHEN OLD.relation='connected_to' OR NEW.relation='connected_to'
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_connected_delete
        AFTER DELETE ON entity_relationships
        WHEN OLD.relation='connected_to'
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_provider_source_update
        AFTER UPDATE OF source_name,source_key,source_version ON source_pages
        WHEN EXISTS(
          SELECT 1 FROM entity_relationships r
          WHERE r.source_page_id=NEW.id AND r.relation='connected_to'
        )
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_map_source_insert
        AFTER INSERT ON map_sources
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_map_source_update
        AFTER UPDATE ON map_sources
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_map_source_delete
        AFTER DELETE ON map_sources
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_map_label_insert
        AFTER INSERT ON map_labels
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_map_label_update
        AFTER UPDATE OF raw_text,map_stem,zone_name,x,y,z ON map_labels
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;

        CREATE TRIGGER IF NOT EXISTS eq_navigation_dirty_map_label_delete
        AFTER DELETE ON map_labels
        BEGIN
          INSERT INTO app_meta(key,value) VALUES('navigation_catalog_dirty','1')
          ON CONFLICT(key) DO UPDATE SET value='1';
        END;
        """
    )
    db.conn.commit()


def ensure_builder_navigation_catalog(db, *, force: bool = False) -> NavigationCatalogRefresh:
    """Refresh stale deterministic navigation derivatives in a writable builder DB.

    This never scans a map folder or provider mirror. It operates only on source facts
    already stored in EverQuestie's SQLite knowledge DB: canonical/client zone identity,
    provider ``connected_to`` relationships, provider-zone bindings, and indexed map
    labels. Packaged RuntimeDatabase knowledge is immutable, so the function is a strict
    no-op there.
    """
    if not getattr(db, "knowledge_writable", True):
        return NavigationCatalogRefresh(False)

    # Clean Travel reads must be effectively free. A current version marker implies
    # the dirty triggers were installed by the successful refresh that wrote it, so
    # avoid repeating schema/index/trigger work on every button click.
    version = db.get_meta("navigation_catalog_version", "")
    dirty = db.get_meta("navigation_catalog_dirty", "1") == "1"
    if not force and version == NAVIGATION_CATALOG_VERSION and not dirty:
        return NavigationCatalogRefresh(False)

    # Ensure the stored map-evidence schema exists before installing triggers that
    # reference it. This creates tables only; it does not crawl or parse local maps.
    MapCatalog(db)
    _install_dirty_triggers(db)

    with db.batch():
        # Match release finalization order: provider identities are projected first so
        # structured provider topology can compile against canonical gameplay zones.
        provider_zones = ProviderZoneReconciliationCatalog(db).reconcile()
        bindings = ZoneMapCatalog(db).reconcile()
        travel = ZoneTravelCatalog(db).reconcile_from_maps()
        provider_travel = ProviderZoneTravelCatalog(db).reconcile()
        db.set_meta("navigation_catalog_version", NAVIGATION_CATALOG_VERSION)
        db.set_meta("navigation_catalog_dirty", "0")
        db.set_meta(
            "navigation_catalog_last_reconcile",
            datetime.now().isoformat(timespec="seconds"),
        )
    return NavigationCatalogRefresh(
        True,
        map_bindings=bindings,
        travel=travel,
        provider_zones=provider_zones,
        provider_travel=provider_travel,
    )
