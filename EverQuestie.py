"""Windows-friendly launcher used by source checkouts and PyInstaller builds."""
from eqquest.runtime_policy import install_runtime_policy
from eqquest.map_loading_policy import install_map_loading_policy
from eqquest.knowledge_coverage_ui import install_knowledge_coverage_ui
from eqquest.packaged_ui_policy import install_packaged_ui_policy
from eqquest.knowledge_relationship_ui import install_knowledge_relationship_navigation_ui
from eqquest.travel_output_ui import install_travel_output_ui
from eqquest.world_profile_ui import install_world_profile_ui
from eqquest.profile_availability_ui import install_profile_availability_ui
from eqquest.activity_pathways_ui import install_activity_pathways_ui
from eqquest.activity_clusters_ui import install_activity_clusters_ui
from eqquest.runtime_mode_ui import install_runtime_mode_ui
from eqquest.runtime import main

if __name__ == "__main__":
    install_runtime_policy()
    install_map_loading_policy()
    install_knowledge_coverage_ui()
    install_packaged_ui_policy()
    install_knowledge_relationship_navigation_ui()
    install_travel_output_ui()
    install_world_profile_ui()
    install_profile_availability_ui()
    install_activity_pathways_ui()
    install_activity_clusters_ui()
    install_runtime_mode_ui()
    main()
