from __future__ import annotations

from .activity_clusters_ui import install_activity_clusters_ui
from .activity_pathway_dismiss_ui import install_activity_pathway_dismiss_ui
from .activity_pathways_ui import install_activity_pathways_ui
from .knowledge_coverage_ui import install_knowledge_coverage_ui
from .knowledge_relationship_ui import install_knowledge_relationship_navigation_ui
from .loot_relevance_ui import install_loot_relevance_ui
from .map_loading_policy import install_map_loading_policy
from .packaged_ui_policy import install_packaged_ui_policy
from .profile_availability_ui import install_profile_availability_ui
from .runtime_mode_ui import install_runtime_mode_ui
from .runtime_policy import install_runtime_policy
from .target_intelligence_ui import install_target_intelligence_ui
from .target_known_drops_live_ui import install_target_known_drops_ui
from .target_personal_sightings_live_ui import install_target_personal_sightings_ui
from .travel_output_ui import install_travel_output_ui
from .world_profile_ui import install_world_profile_ui
from .zone_opportunities_ui import install_zone_opportunities_ui


def install_application_layers() -> None:
    """Install the complete EverQuestie runtime/UI decorator stack in one order.

    Both supported launchers call this function. Keeping the composition here prevents
    `EverQuestie.py` and `python -m eqquest` from silently exposing different runtime
    behavior as new local-first intelligence surfaces are added.
    """
    install_runtime_policy()
    install_map_loading_policy()
    install_knowledge_coverage_ui()
    install_packaged_ui_policy()
    install_knowledge_relationship_navigation_ui()
    install_travel_output_ui()
    install_world_profile_ui()
    install_profile_availability_ui()
    install_activity_pathways_ui()
    install_activity_pathway_dismiss_ui()
    install_activity_clusters_ui()
    install_zone_opportunities_ui()
    install_loot_relevance_ui()
    install_target_intelligence_ui()
    install_target_known_drops_ui()
    install_target_personal_sightings_ui()
    install_runtime_mode_ui()
