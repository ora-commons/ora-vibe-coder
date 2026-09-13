"""Double-click a supplied installer entry, or invoke this shared Python entry."""
import sys
from ora_vibe_coder.__main__ import main

if __name__ == "__main__":
    sys.argv.insert(1, "--install")
    main()
