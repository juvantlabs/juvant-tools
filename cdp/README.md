# cdp/

Chrome DevTools Protocol (CDP) sniffers for reverse-engineering vendor
web flows. Standalone scripts — run directly via
`python3 cdp/<script>.py`.

## Tools

| Script | What it does |
|---|---|
| [`http_spy.py`](http_spy.py) | Captures HTTP requests / responses on a live browser tab via CDP. Filters by URL substring, parses JSON bodies, and extracts UUIDs and `*Id` / `*_id` fields for quick scanning of identifier surfaces. |
| [`websocket_spy.py`](websocket_spy.py) | Captures every WebSocket frame (sent and received) on a live browser tab via CDP, including nested iframe sub-targets. Decodes UTF-8 / JSON automatically; falls back to hex for binary frames. Optional URL filter and connection labels. |

## Prerequisites

```bash
pip install websockets requests
```

A Chromium-based browser launched with remote debugging enabled:

```bash
# macOS Edge example
/Applications/Microsoft\ Edge.app/Contents/MacOS/Microsoft\ Edge \
  --remote-debugging-port=9222 --no-first-run

# Linux Chrome example
google-chrome --remote-debugging-port=9222 --no-first-run
```

The default CDP host is `http://localhost:9222`. Override with
`--cdp-host` if needed.

## Quick examples

```bash
# Capture all REST calls to /api/* on the active tab
python3 cdp/http_spy.py --url-filter /api/

# Filter by multiple URL substrings (logical OR), pre-select tab
python3 cdp/http_spy.py \
  --url-filter /api/ --url-filter login \
  --tab-filter mydomain.com

# Capture every WebSocket frame on the active tab
python3 cdp/websocket_spy.py

# Capture only specific WS, with custom labels in the log
python3 cdp/websocket_spy.py \
  --ws-filter zoom.us \
  --label zoom.us=ZOOM --label chime=CHIME
```

## Why standalone (not packaged)

These tools are debug aids — used live during reverse-engineering
sessions, then idle for weeks. They ship as scripts rather than as
versioned CLI commands so they can be tweaked in place when a vendor's
network shape changes, without having to release a new package version.
