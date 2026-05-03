"""
websocket_spy.py — CDP WebSocket frame spy (generic)
=====================================================
Connects to a running Chrome / Edge instance launched with
`--remote-debugging-port=9222`, attaches to any browser tab (and its
nested iframes via Target.setAutoAttach), and logs every WebSocket frame
with its full payload.

Use `--ws-filter` to restrict logging to connections whose URL contains a
substring (e.g. "myvendor", "zoom.us"). Omit to capture all connections.

Use `--label SUBSTRING=NAME` (repeatable) to tag each log line with a
short label whenever the WS URL contains that substring — useful when
sniffing several different connections in the same session.

Usage:
  1. Launch Edge / Chrome with remote debugging:
       /Applications/Microsoft\\ Edge.app/Contents/MacOS/Microsoft\\ Edge \\
         --remote-debugging-port=9222 --no-first-run
  2. Open the target page in that browser.
  3. Run:
       python3 websocket_spy.py
       python3 websocket_spy.py --ws-filter zoom.us
       python3 websocket_spy.py --label zoom.us=ZOOM --label chime=CHIME
  4. Press Ctrl+C to stop; output is also saved to wss_spy.log.

Dependencies: pip install websockets requests
"""

import argparse
import asyncio
import base64
import json
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


def decode_frame(raw: bytes, direction: str) -> str:
    lines = []
    if len(raw) < 2:
        lines.append(f"  [{direction}] SHORT: {raw.hex()}")
        return "\n".join(lines)

    try:
        text = raw.decode("utf-8")
        try:
            obj = json.loads(text)
            lines.append(f"  [{direction}] JSON: {json.dumps(obj, indent=None, separators=(',', ':'))}")
        except json.JSONDecodeError:
            lines.append(f"  [{direction}] TEXT: {text}")
        return "\n".join(lines)
    except UnicodeDecodeError:
        pass

    # Binary frame — try to extract an embedded JSON payload
    json_start = raw.find(b"{")
    if json_start != -1:
        header_hex = raw[:json_start].hex()
        json_bytes = raw[json_start:]
        try:
            text = json_bytes.decode("utf-8", errors="replace")
            try:
                obj = json.loads(text)
                lines.append(f"  [{direction}] BINARY({len(raw)}B) header={header_hex}")
                lines.append(f"  [{direction}] JSON: {json.dumps(obj, indent=None, separators=(',', ':'))}")
            except json.JSONDecodeError:
                lines.append(f"  [{direction}] BINARY({len(raw)}B) header={header_hex}")
                lines.append(f"  [{direction}] TEXT: {text}")
        except Exception:
            lines.append(f"  [{direction}] BINARY({len(raw)}B): {raw.hex()}")
    else:
        lines.append(f"  [{direction}] BINARY({len(raw)}B): {raw.hex()}")
    return "\n".join(lines)


def make_label_fn(label_map: list[tuple[str, str]]):
    """Return a function url -> label using a list of (substring, name) rules."""
    def conn_label(url: str) -> str:
        url_l = url.lower()
        for substring, name in label_map:
            if substring.lower() in url_l:
                return name
        return "WS"
    return conn_label


def parse_label_arg(value: str) -> tuple[str, str]:
    """Parse 'substring=NAME' or raise."""
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            f"--label expects SUBSTRING=NAME, got: {value!r}"
        )
    substring, name = value.split("=", 1)
    if not substring or not name:
        raise argparse.ArgumentTypeError(
            f"--label expects non-empty SUBSTRING and NAME, got: {value!r}"
        )
    return substring, name


async def spy_on_tab(ws_url: str, output_file: str, ws_filter: str, conn_label):
    print(f"[*] Connecting to CDP tab: {ws_url}")
    filter_desc = f'containing "{ws_filter}"' if ws_filter else "ALL"
    print(f"[*] Capturing WebSocket connections {filter_desc}")
    log_lines = []

    def log(msg: str):
        print(msg)
        log_lines.append(msg)

    async with websockets.connect(ws_url, max_size=100 * 1024 * 1024) as cdp:
        _id = 0

        async def send(method, params=None):
            nonlocal _id
            _id += 1
            await cdp.send(json.dumps({"id": _id, "method": method, "params": params or {}}))

        await send("Network.enable")
        # Flatten all sub-targets (iframes) into this session so their Network
        # events are delivered here too — captures WS connections inside iframes.
        await send("Target.setAutoAttach", {
            "autoAttach": True,
            "waitForDebuggerOnStart": False,
            "flatten": True,
        })

        log(f"[*] Network.enable + Target.setAutoAttach(flatten=True) done")
        log("[*] Press Ctrl+C to stop.")
        log("[*] TIP: reload the page now so all WS URLs are captured from the start.\n")

        ws_connections: dict[str, str] = {}
        frame_count = 0
        start = time.time()

        try:
            while True:
                msg = await cdp.recv()
                event = json.loads(msg)
                method = event.get("method", "")
                params = event.get("params", {})

                if method == "Target.attachedToTarget":
                    session_id = params.get("sessionId", "")
                    target_info = params.get("targetInfo", {})
                    target_url  = target_info.get("url", "")
                    log(f"\n[FRAME ATTACHED] sessionId={session_id} url={target_url[:100]}")
                    await cdp.send(json.dumps({
                        "id": _id + 1000,
                        "sessionId": session_id,
                        "method": "Network.enable",
                        "params": {},
                    }))

                elif method == "Network.webSocketCreated":
                    url = params.get("url", "")
                    rid = params.get("requestId", "")
                    ws_connections[rid] = url
                    if not ws_filter or ws_filter.lower() in url.lower():
                        log(f"\n[WS OPEN] [{conn_label(url)}] requestId={rid}")
                        log(f"  URL: {url}")

                elif method == "Network.webSocketClosed":
                    rid = params.get("requestId", "")
                    if rid in ws_connections:
                        url = ws_connections[rid]
                        if not ws_filter or ws_filter.lower() in url.lower():
                            log(f"\n[WS CLOSE] [{conn_label(url)}] url={url[:120]}")
                        del ws_connections[rid]

                elif method in ("Network.webSocketFrameSent", "Network.webSocketFrameReceived"):
                    rid = params.get("requestId", "")

                    if rid not in ws_connections:
                        ws_connections[rid] = "(pre-existing — URL unknown)"
                        log(f"\n[WS SEEN] requestId={rid} (connection was open before spy attached)")

                    url = ws_connections[rid]
                    if ws_filter and "(pre-existing" not in url and ws_filter.lower() not in url.lower():
                        continue

                    ts = time.time() - start
                    direction = "TX" if method == "Network.webSocketFrameSent" else "RX"
                    response = params.get("response", {})
                    payload_b64 = response.get("payloadData", "")
                    opcode_type = response.get("opcode", 0)

                    frame_count += 1
                    log(f"\n--- Frame #{frame_count} t={ts:.2f}s [{direction}] [{conn_label(url)}] WS-opcode={opcode_type} ---")
                    log(f"  URL: {url[:100]}")

                    if opcode_type == 2:
                        try:
                            raw = base64.b64decode(payload_b64)
                        except Exception:
                            raw = b""
                        log(decode_frame(raw, direction))
                    else:
                        log(f"  [{direction}] TEXT: {payload_b64[:600]}")

        except KeyboardInterrupt:
            log("\n[*] Stopped by user.")
        except Exception as e:
            log(f"\n[!] Error: {e}")
        finally:
            with open(output_file, "w") as f:
                f.write("\n".join(log_lines))
            print(f"\n[*] Log saved to {output_file} ({frame_count} frames)")


async def main():
    parser = argparse.ArgumentParser(description="CDP WebSocket frame spy (generic)")
    parser.add_argument("--cdp-host",    default="http://localhost:9222", help="CDP host (default: http://localhost:9222)")
    parser.add_argument("--output-file", default="wss_spy.log",           help="Output log file (default: wss_spy.log)")
    parser.add_argument("--ws-filter",   default="",                       help="Only log WS connections whose URL contains this string (default: all)")
    parser.add_argument("--tab-filter",  default="",                       help="Auto-select tab whose URL or title contains this string")
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        type=parse_label_arg,
        metavar="SUBSTRING=NAME",
        help="Tag log lines with NAME when a WS URL contains SUBSTRING. Repeatable. Example: --label zoom.us=ZOOM",
    )
    args = parser.parse_args()

    conn_label = make_label_fn(args.label)

    targets = get_targets(args.cdp_host)
    candidates = []
    for t in targets:
        if t.get("type") != "page":
            continue
        ws_dbg = t.get("webSocketDebuggerUrl", "")
        if not ws_dbg:
            continue
        candidates.append((t.get("url", ""), ws_dbg, t.get("title", "")))

    if not candidates:
        print("[!] No inspectable page tabs found.")
        sys.exit(1)

    print("[*] Available tabs:")
    for i, (url, _, title) in enumerate(candidates):
        print(f"  [{i}] {title[:60]} — {url[:80]}")

    selected = None
    if args.tab_filter:
        for i, (url, ws_dbg, title) in enumerate(candidates):
            if args.tab_filter.lower() in url.lower() or args.tab_filter.lower() in title.lower():
                selected = (url, ws_dbg, title)
                print(f"\n[*] Auto-selected tab [{i}] (matches --tab-filter {args.tab_filter!r}): {title[:60]}")
                break

    if not selected:
        if len(candidates) == 1:
            selected = candidates[0]
            print(f"\n[*] Using only tab: {selected[2][:60]}")
        else:
            idx = int(input("\nSelect tab index: "))
            selected = candidates[idx]

    await spy_on_tab(selected[1], args.output_file, args.ws_filter, conn_label)


if __name__ == "__main__":
    asyncio.run(main())
