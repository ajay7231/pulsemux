"""Export public API contracts without connecting to the database."""
import json
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "worker-py"))
os.environ["PLATFORM_ENV"] = "development"
from app.web_server import app
output = root / "dashboard" / "openapi.json"
output.write_text(json.dumps(app.openapi(), indent=2) + "\n")
print("Exported dashboard/openapi.json")
