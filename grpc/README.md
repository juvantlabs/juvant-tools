# grpc/

Interactive gRPC client / explorer. Standalone script — run directly via
`python3 grpc/explorer.py`.

## Tools

| Script | What it does |
|---|---|
| [`explorer.py`](explorer.py) | Connect to a gRPC server, discover its services (via server reflection or by compiling local `.proto` files), pick a method through numbered menus, edit the request JSON in your editor, invoke, and pretty-print the response. Supports unary-unary and server-streaming methods. |

## Prerequisites

```bash
pip install grpcio grpcio-reflection grpcio-tools protobuf
```

These dependencies are intentionally NOT pulled in by `juvant-tools`
itself — `grpcio` is a heavy install (~200 MB) and most users only
need it ad-hoc.

## Discovery (auto-fallback chain)

The explorer tries discovery in this order:

1. **Server reflection** (default) — if the server exposes
   `grpc.reflection.v1alpha.ServerReflection`, it discovers services
   and fetches their `FileDescriptorProto`s over the wire. No local
   `.proto` files needed.
2. **Proto-dir fallback** — if reflection fails (UNIMPLEMENTED, channel
   error, zero services) and `--proto-dir PATH` is supplied, it
   compiles every `.proto` under PATH with `grpc_tools.protoc` and
   uses the resulting descriptors.
3. **Hard fail** — if both above fail (or no `--proto-dir` was given),
   exits with a clear error message.

```bash
# Reflection only (most dev/staging gRPC servers)
python3 grpc/explorer.py --host localhost:50051

# Reflection with proto-dir as automatic fallback
python3 grpc/explorer.py --host api.example.com:443 --tls --proto-dir ./protos
```

### Skip reflection entirely (`--no-reflection`)

Useful when local `.proto` files are more up-to-date than the server's
reflected schema, or when the server's reflection cooperates only
partially. Requires `--proto-dir`.

```bash
python3 grpc/explorer.py --host localhost:50051 \
  --no-reflection --proto-dir ./protos
```

## Invocation modes (auto-detected)

### Interactive (default)

```bash
python3 grpc/explorer.py --host localhost:50051
```

Walks numbered menus to pick service + method, then opens an editor on
a JSON template pre-filled with default values. Requires a TTY.

### Scripted

Pass `--service`, `--method`, and one of `--payload` / `--payload-file`.
The explorer skips menus and editors:

```bash
# Unary request — payload is a JSON object
python3 grpc/explorer.py --host localhost:50051 \
  --service my.pkg.MyService \
  --method GetThing \
  --payload '{"id":"abc"}'
```

```bash
# Streaming request (client-streaming or bidi-streaming) — payload is a JSON array,
# each element is one request message in the stream
python3 grpc/explorer.py --host localhost:50051 \
  --service my.pkg.MyService \
  --method UploadStream \
  --payload '[{"chunk":"a"},{"chunk":"b"},{"chunk":"c"}]'
```

```bash
# Payload from file (handy for large or multi-line JSON)
python3 grpc/explorer.py --host localhost:50051 \
  --service my.pkg.MyService \
  --method GetThing \
  --payload-file ./request.json
```

## Editor discovery (interactive mode only)

Git-style fallback chain:

1. `--editor CMD`               (explicit override)
2. `$VISUAL`                    (env var)
3. `$EDITOR`                    (env var)
4. Platform default             (`notepad` on Windows; `nano` then `vi` on Unix)
5. File mode                    (auto when no editor found, or `--no-editor`):
                                 prints the tempfile path and waits for Enter

The script prints a brief save-and-exit hint above the editor launch
(e.g. _Press Ctrl+X then Y then Enter_ for nano), so the workflow
doesn't break if you're not used to the chosen editor.

If you prefer to use a GUI editor (VS Code, Sublime, etc.), use
`--no-editor`: the script prints the path of the prepared JSON
template, you open it in whatever editor you want, save, return to
the terminal, and press Enter.

## Authentication

| Flag | Purpose |
|---|---|
| `--tls` | Open a `secure_channel` instead of insecure (default). |
| `--ca-cert PATH` | Custom CA certificate for verifying the server. |
| `--client-cert PATH` + `--client-key PATH` | mTLS — client-side certificate. |
| `--metadata KEY=VAL` (repeatable) | Per-call header. Use for bearer tokens, API keys, custom auth headers. |

Examples:

```bash
# Public TLS endpoint with a Bearer token in metadata
python3 grpc/explorer.py --host api.example.com:443 --tls \
  --metadata authorization='Bearer eyJhbGc...'

# mTLS
python3 grpc/explorer.py --host secure.example.com:443 --tls \
  --ca-cert ./ca.pem --client-cert ./client.pem --client-key ./client.key
```

## Streaming support

| Method type | Status | Behavior |
|---|---|---|
| unary-unary | ✓ | One request, one response. |
| server-streaming | ✓ | One request, then the explorer reads to EOF and prints each response message. |
| client-streaming | ✓ | Sends every element of the JSON array request payload, then reads the single response. |
| bidi-streaming | ✓ | Sends every element of the JSON array, then reads to EOF. **No interleaving** — all requests go before any responses are read. Adequate for exploration; not a full bidi simulator. |

For streaming-request methods (client-streaming or bidi-streaming), the
payload must be a JSON array (`[{...}, {...}, ...]`); each element is
one message in the request stream. In interactive mode, the editor
opens a JSON array template pre-filled with one default message.

## Quick start examples

```bash
# Local gRPC dev server with reflection
python3 grpc/explorer.py --host localhost:50051

# Public gRPC endpoint with TLS + Bearer auth
python3 grpc/explorer.py --host api.example.com:443 --tls \
  --metadata authorization='Bearer …'

# Server without reflection — supply local .proto dir as fallback
python3 grpc/explorer.py --host api.example.com:443 --tls \
  --proto-dir ./vendor-protos

# Force proto-dir mode (skip reflection)
python3 grpc/explorer.py --host localhost:50051 \
  --no-reflection --proto-dir ./vendor-protos

# Scripted unary invocation (no menus, no editor)
python3 grpc/explorer.py --host localhost:50051 \
  --service helloworld.Greeter --method SayHello \
  --payload '{"name":"world"}'

# Scripted client-streaming or bidi-streaming
python3 grpc/explorer.py --host localhost:50051 \
  --service helloworld.Greeter --method CollectHello \
  --payload '[{"name":"alice"},{"name":"bob"},{"name":"carol"}]'
```

## Why standalone (not packaged)

This is a debug / exploration tool: connect to a server, poke at it,
disconnect. The `grpcio` dependency is heavy (~200 MB installed) and
most users of `juvant-tools` will never need it. Keeping it as a
standalone script means installing the gRPC stack is opt-in and the
package surface stays slim.
