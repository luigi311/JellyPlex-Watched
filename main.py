import sys

if __name__ == "__main__":
    # Check python version 3.12 or higher
    if not (3, 12) <= tuple(map(int, sys.version_info[:2])):
        print("This script requires Python 3.12 or higher")
        sys.exit(1)

    from src.main import main

    main()
