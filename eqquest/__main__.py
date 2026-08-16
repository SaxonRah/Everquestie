from .runtime_policy import install_runtime_policy
from .map_loading_policy import install_map_loading_policy
from .knowledge_coverage_ui import install_knowledge_coverage_ui
from .packaged_ui_policy import install_packaged_ui_policy
from .knowledge_relationship_ui import install_knowledge_relationship_navigation_ui
from .travel_output_ui import install_travel_output_ui
from .world_profile_ui import install_world_profile_ui
from .profile_availability_ui import install_profile_availability_ui
from .target_intelligence_ui import install_target_intelligence_ui
from .runtime_mode_ui import install_runtime_mode_ui
from .runtime import main

if __name__ == "__main__":
    install_runtime_policy()
    install_map_loading_policy()
    install_knowledge_coverage_ui()
    install_packaged_ui_policy()
    install_knowledge_relationship_navigation_ui()
    install_travel_output_ui()
    install_world_profile_ui()
    install_profile_availability_ui()
    install_target_intelligence_ui()
    install_runtime_mode_ui()
    main()
