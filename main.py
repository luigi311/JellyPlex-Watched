import os
import sys

from dotenv import load_dotenv
from loguru import logger

if __name__ == "__main__":
    # Check python version 3.6 or higher
    if not (3, 6) <= tuple(map(int, sys.version_info[:2])):
        print("This script requires Python 3.6 or higher")
        sys.exit(1)

    from src.main import main

    main()
