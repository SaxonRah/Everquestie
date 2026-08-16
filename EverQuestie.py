"""Windows-friendly launcher used by source checkouts and PyInstaller builds."""
from eqquest.bootstrap import install_application_layers
from eqquest.runtime import main

if __name__ == "__main__":
    install_application_layers()
    main()
