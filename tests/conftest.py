import os
import sys
import tempfile

# tests must never read or write the real user settings
os.environ["GESTYQ_CONFIG"] = os.path.join(tempfile.mkdtemp(prefix="gestyq-test-"), "config.json")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
