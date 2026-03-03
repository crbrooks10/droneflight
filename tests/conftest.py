import sys
import pathlib

# ensure the project root is on sys.path so tests can import the package
root = pathlib.Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(root))
