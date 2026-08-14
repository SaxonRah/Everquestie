from .runtime_policy import install_runtime_policy
from .map_loading_policy import install_map_loading_policy
from .knowledge_coverage_ui import install_knowledge_coverage_ui
from .runtime import main

if __name__ == "__main__":
    install_runtime_policy()
    install_map_loading_policy()
    install_knowledge_coverage_ui()
    main()
