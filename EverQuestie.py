"""Windows-friendly launcher used by source checkouts and PyInstaller builds."""
from eqquest.runtime_policy import install_runtime_policy
from eqquest.map_loading_policy import install_map_loading_policy
from eqquest.knowledge_coverage_ui import install_knowledge_coverage_ui
from eqquest.runtime import main

if __name__ == "__main__":
    install_runtime_policy()
    install_map_loading_policy()
    install_knowledge_coverage_ui()
    main()
