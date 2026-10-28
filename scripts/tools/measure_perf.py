# -*- coding: utf-8 -*-
"""用 Edge headless 实测单文件页面的首屏性能。

用法：python scripts/tools/measure_perf.py [--json]
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILT = os.path.join(ROOT, "software", "考研核心词.html")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

PROBE = """
<script>
(function(){
  function report(){
    var nav = performance.getEntriesByType('navigation')[0] || {};
    var paints = {};
    performance.getEntriesByType('paint').forEach(function(p){ paints[p.name] = p.startTime; });
    var mark = window.__firstCardAt || 0;
    var data = {
      fcp: Math.round(paints['first-contentful-paint'] || 0),
      dcl: Math.round(nav.domContentLoadedEventEnd || 0),
      load: Math.round(nav.loadEventEnd || 0),
      firstCard: Math.round(mark),
      nodes: document.querySelectorAll('*').length
    };
    document.title = 'PERF:' + JSON.stringify(data);
  }
  window.addEventListener('load', function(){ setTimeout(report, 0); });
})();
</script>
"""


def measure():
    html = io.open(BUILT, encoding="utf-8").read()
    html = html.replace("</body>", PROBE + "</body>")
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "_perf.html")
    io.open(path, "w", encoding="utf-8").write(html)
    r = subprocess.run(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--user-data-dir=" + os.path.join(tmp, "profile"),
         "--virtual-time-budget=6000", "--dump-dom",
         "file:///" + path.replace("\\", "/")],
        capture_output=True, timeout=120,
    )
    m = re.search(r"PERF:(\{[^<]*\})", r.stdout.decode("utf-8", "replace"))
    if not m:
        return None
    return json.loads(m.group(1))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data = measure()
    if data is None:
        print(json.dumps({"error": "测量失败，Edge headless 未返回性能标记"}), file=sys.stderr)
        return 1
    data["size_kb"] = os.path.getsize(BUILT) // 1024
    if "--json" in sys.argv:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print("首屏性能")
        for k, v in data.items():
            print("  %-10s %s" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
