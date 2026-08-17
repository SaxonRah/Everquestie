from __future__ import annotations


def location_is_actionable(row) -> bool:
    """Return whether one location row may drive a player Map/Travel action.

    ``navigable`` remains the geometry/zone projection predicate used by Knowledge to
    describe a coordinate-bearing fact. Actionability is deliberately stricter:

    * imported/provider ``entity_location`` rows need their own source page;
    * world-context location rows likewise need their own source page;
    * linked native-map rows carry provenance through the map catalog, so a concrete
      ``map_label_id`` is their independent evidence carrier.

    This keeps legacy/manual rows visible without silently promoting them into gameplay
    guidance simply because they happen to contain canonical X/Y coordinates.
    """
    if not bool(getattr(row, "navigable", False)):
        return False

    evidence_type = str(getattr(row, "evidence_type", "") or "")
    if evidence_type == "map_label":
        return getattr(row, "map_label_id", None) is not None

    return getattr(row, "source_page_id", None) is not None


def location_actionability_note(row) -> str:
    """Explain the evidence-only case without redefining geometry navigability.

    Candidate/unresolved zone projection has its own more specific presentation in the
    location renderers. This note covers the subtler case where a row has canonical X/Y
    geometry but lacks the reviewed evidence carrier required by player Map/Travel
    actions.
    """
    if location_is_actionable(row) or not bool(getattr(row, "navigable", False)):
        return ""

    evidence_type = str(getattr(row, "evidence_type", "") or "")
    if evidence_type == "map_label":
        return "evidence only: linked map provenance is incomplete; not map-targetable"
    return "evidence only: missing reviewed provenance; not map-targetable"


def relationship_is_actionable(fact) -> bool:
    """Return whether a semantic relationship is reviewed enough for player action."""
    return getattr(fact, "source_page_id", None) is not None
