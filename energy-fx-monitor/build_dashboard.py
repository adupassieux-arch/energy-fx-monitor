"""Injects data/data.json into template.html and writes the published pages.

- index.html          full HTML document for GitHub Pages
- dist/artifact.html  same page without the document wrapper (for a claude.ai preview)
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
data = json.loads((ROOT / "data" / "data.json").read_text())
page = (ROOT / "template.html").read_text().replace(
    "/*__DATA__*/null", json.dumps(data, separators=(",", ":")))

(ROOT / "dist").mkdir(exist_ok=True)
(ROOT / "dist" / "artifact.html").write_text(page)

doc = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
       '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
       '<style>body{margin:0}</style>\n</head>\n<body>\n' + page + '\n</body>\n</html>\n')
(ROOT / "index.html").write_text(doc)
print("Built index.html and dist/artifact.html")
