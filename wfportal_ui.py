#!/usr/bin/env python3
"""wfportal_ui - wfportal をブラウザから操作するローカルUI (標準ライブラリのみ)

    python wfportal_ui.py              # http://127.0.0.1:8765 を開く
    python wfportal_ui.py --port 9000 --no-open --data-dir ./data

自分のPCの中だけで動き(127.0.0.1にだけ待ち受け)、データは wfportal.py と同じ場所を使います。
"""
from __future__ import annotations

from wfp.api.server import main

if __name__ == "__main__":
    main()
