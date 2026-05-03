"""
http_spy.py — CDP HTTP request/response spy
=============================================
Connects to a running Chrome / Edge instance launched with
`--remote-debugging-port=9222`, attaches to a browser tab, and logs every
HTTP request/response whose URL contains any of the configured filter
substrings. Captures full response bodies, parses JSON when possible, and
extracts UUIDs and `*Id` / `*_id` fields from the body for quick scanning.

Useful when reverse-engineering a vendor web flow to find stable
identifiers (account UUIDs, cross-session user IDs, etc.) that are not
visible at the network-protocol layer.

Usage:
  1. Launch Edge / Chrome with remote debugging:
       /Applications/Microsoft\\ Edge.app/Contents/MacOS/Microsoft\\ Edge \\
         --remote-debugging-port=9222 --no-first-run
  2. In that browser, navigate to the target page and start the flow.
  3. Run:
       python3 http_spy.py --url-filter /api/ --url-filter mydomain.com
       python3 http_spy.py --url-filter /api/ --tab-filter mydomain.com
  4. Complete the flow; press Ctrl+C to stop. Output is written to the
     log file as captured.

Dependencies: pip install websockets requests
"""

import argparse
import asyncio
import base64
import json
import re
import sys
import time

import requests
import websockets


def get_targets(cdp_host: str):
    try:
        r = requests.get(f"{cdp_host}/json", timeout=5)
        return r.json()
    except Exception as e:
        print(f"[!] Cannot connect to CDP at {cdp_host}: {e}")
        print("    Make sure Edge/Chrome is running with --remote-debugging-port=9222")
        sys.exit(1)


def _ts(start: float) -> str:
    return f"{time.time() - start:.2f}s"


def matches_filter(url: str, filters: list[str]) -> bool:
    return any(f in url for f in filters)


async def spy_on_tab(ws_url: str, log_path: str, url_filters: list[str]) -> None:
    start = time.time()
    pending: dict[str, dict] = {}
    pending_cmds: dict[int, asyncio.Future] = {}
    cmd_counter = [10]
    ready_queue: asyncio.Queue = asyncio.Queue()

    with open(log_path, "a") as log_f:
        def log(line: str) -> None:
            print(line)
            log_f.write(line + "\n")
            log_f.flush()

        async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Network.enable"}))

            log("[*] Network.enable sent")
            log(f"[*] Capturing requests matching: {url_filters}")
            log("[*] Drive the flow in the browser now.")
            log("")

            async def send_cmd(method: str, params: dict) -> "asyncio.Future[dict]":
                cmd_counter[0] += 1
                cid = cmd_counter[0]
                fut: asyncio.Future = asyncio.get_event_loop().create_future()
                pending_cmds[cid] = fut
                await ws.send(json.dumps({"id": cid, "method": method, "params": params}))
                return fut

            async def reader() -> None:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue

                    if "id" in msg and msg["id"] in pending_cmds:
                        fut = pending_cmds.pop(msg["id"])
                        if not fut.done():
                            fut.set_result(msg.get("result", {}))
                        continue

                    method = msg.get("method", "")
                    params = msg.get("params", {})

                    if method == "Network.requestWillBeSent":
                        req = params.get("request", {})
                        url = req.get("url", "")
                        if not matches_filter(url, url_filters):
                            continue
                        rid = params["requestId"]
                        pending[rid] = {
                            "url": url,
                            "method": req.get("method", "?"),
                            "post_data": req.get("postData", ""),
                            "ts": _ts(start),
                        }

                    elif method == "Network.responseReceived":
                        rid = params["requestId"]
                        resp_info = params.get("response", {})
                        url = resp_info.get("url", "")
                        if rid not in pending:
                            if not matches_filter(url, url_filters):
                                continue
                            pending[rid] = {
                                "url": url,
                                "method": "?",
                                "post_data": "",
                                "ts": _ts(start),
                            }
                        pending[rid]["status"] = resp_info.get("status")

                    elif method == "Network.loadingFinished":
                        rid = params["requestId"]
                        if rid in pending:
                            info = pending.pop(rid)
                            await ready_queue.put((rid, info))

            async def printer() -> None:
                while True:
                    rid, info = await ready_queue.get()

                    try:
                        fut = await send_cmd("Network.getResponseBody", {"requestId": rid})
                        result = await asyncio.wait_for(fut, timeout=5.0)
                        body_raw = result.get("body", "")
                        if result.get("base64Encoded"):
                            body_raw = base64.b64decode(body_raw).decode("utf-8", errors="replace")
                    except Exception:
                        body_raw = ""

                    url    = info["url"]
                    method = info["method"]
                    status = info.get("status", "?")
                    ts     = info["ts"]

                    log(f"\n{'─' * 70}")
                    log(f"[{ts}] {method} {url}")
                    log(f"  Status: {status}")

                    if info.get("post_data"):
                        log(f"  Request body: {info['post_data'][:500]}")

                    if body_raw:
                        try:
                            parsed = json.loads(body_raw)
                            pretty = json.dumps(parsed, indent=2)
                            if len(pretty) > 4000:
                                pretty = pretty[:4000] + "\n  ... (truncated)"
                            log(f"  Response body:\n{pretty}")
                        except Exception:
                            log(f"  Response body (raw): {body_raw[:2000]}")

                        uuids = re.findall(
                            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                            body_raw, re.I,
                        )
                        id_fields = re.findall(
                            r'"(?:userId|user_id|externalId|attendeeId|'
                            r'accountId|personId|sub|uid|id|uuid)":\s*"([^"]+)"',
                            body_raw, re.I,
                        )
                        if uuids:
                            log(f"  * UUIDs found: {list(dict.fromkeys(uuids))}")
                        if id_fields:
                            log(f"  * ID fields found: {list(dict.fromkeys(id_fields))}")
                    else:
                        log("  Response body: (empty or not available)")

            try:
                await asyncio.gather(reader(), printer())
            except (KeyboardInterrupt, asyncio.CancelledError):
                log("\n[*] Stopped.")


async def spy(cdp_host: str, log_path: str, url_filters: list[str], tab_filter: str) -> None:
    targets = get_targets(cdp_host)

    candidates = []
    for t in targets:
        if t.get("type") != "page":
            continue
        if not t.get("webSocketDebuggerUrl"):
            continue
        candidates.append((t.get("url", ""), t["webSocketDebuggerUrl"], t.get("title", "")))

    if not candidates:
        print("[!] No inspectable page tabs found.")
        sys.exit(1)

    print("[*] Available tabs:")
    for i, (url, _, title) in enumerate(candidates):
        print(f"  [{i}] {title[:60]} -- {url[:80]}")

    selected = None
    if tab_filter:
        for i, (url, ws_dbg, title) in enumerate(candidates):
            if tab_filter.lower() in url.lower() or tab_filter.lower() in title.lower():
                selected = (url, ws_dbg, title)
                print(f"\n[*] Auto-selected tab [{i}] (matches --tab-filter {tab_filter!r}): {title[:60]}")
                break

    if selected is None:
        if len(candidates) == 1:
            selected = candidates[0]
            print(f"\n[*] Using only available tab: {selected[2][:60]}")
        else:
            try:
                idx = int(input("\n[?] Select tab index: "))
                selected = candidates[idx]
            except (ValueError, IndexError):
                print("[!] Invalid selection.")
                sys.exit(1)

    tab_url, ws_url, title = selected
    print(f"[*] Attaching to tab: {tab_url[:80]}")
    print(f"[*] CDP WS: {ws_url[:80]}")
    print(f"[*] Logging to: {log_path}")
    print()

    with open(log_path, "w") as f:
        f.write(f"[*] HTTP spy started -- attached to: {tab_url}\n\n")

    await spy_on_tab(ws_url, log_path, url_filters)


def main() -> None:
    p = argparse.ArgumentParser(
        description="CDP HTTP request/response spy"
    )
    p.add_argument(
        "--cdp-host", default="http://localhost:9222",
        help="CDP host URL (default: http://localhost:9222)",
    )
    p.add_argument(
        "--output-file", default="http_spy.log",
        help="Output log file (default: http_spy.log)",
    )
    p.add_argument(
        "--url-filter", action="append", default=[], metavar="SUBSTRING", required=True,
        help="Only capture requests whose URL contains this substring. "
             "Repeat to match any of several substrings (logical OR). At least one is required.",
    )
    p.add_argument(
        "--tab-filter", default="", metavar="SUBSTRING",
        help="Auto-select the tab whose URL or title contains this substring. "
             "If omitted and multiple tabs are inspectable, you will be prompted.",
    )
    args = p.parse_args()
    asyncio.run(spy(args.cdp_host, args.output_file, args.url_filter, args.tab_filter))


if __name__ == "__main__":
    main()
