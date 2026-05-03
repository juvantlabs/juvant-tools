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

## Discovery modes

### Reflection (default)

If the gRPC server exposes the
`grpc.reflection.v1alpha.ServerReflection` service, the explorer
discovers services and fetches their `FileDescriptorProto`s over the
wire. No local `.proto` files needed.

```bash
python3 grpc/explorer.py --host localhost:50051
```

Most modern gRPC servers in dev/staging have reflection on. Production
sometimes turns it off — fall back to proto-dir mode below.

### Proto-dir (fallback for servers without reflection)

Pass a directory containing your `.proto` files. The explorer compiles
them with `grpc_tools.protoc` to a tempdir, imports the generated
`_pb2.py` modules, and uses the resulting descriptors.

```bash
python3 grpc/explorer.py --host api.example.com:443 --tls --proto-dir ./protos
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
python3 grpc/explorer.py --host localhost:50051 \
  --service my.pkg.MyService \
  --method GetThing \
  --payload '{"id":"abc"}'
```

```bash
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

| Method type | v0.1 |
|---|---|
| unary-unary | ✓ |
| server-streaming | ✓ (reads until end-of-stream, prints each message) |
| client-streaming | not yet (v0.2) |
| bidi-streaming | not yet (v0.2) |

Pick a client-streaming or bidi-streaming method in interactive mode
and the explorer prints a clear message and returns to the menu.

## Quick start examples

```bash
# Local gRPC dev server with reflection
python3 grpc/explorer.py --host localhost:50051

# Public gRPC endpoint with TLS + Bearer auth
python3 grpc/explorer.py --host api.example.com:443 --tls \
  --metadata authorization='Bearer …'

# Server without reflection — supply local .proto dir
python3 grpc/explorer.py --host api.example.com:443 --tls \
  --proto-dir ./vendor-protos

# Scripted invocation (no menus, no editor)
python3 grpc/explorer.py --host localhost:50051 \
  --service helloworld.Greeter --method SayHello \
  --payload '{"name":"world"}'
```

## Why standalone (not packaged)

This is a debug / exploration tool: connect to a server, poke at it,
disconnect. The `grpcio` dependency is heavy (~200 MB installed) and
most users of `juvant-tools` will never need it. Keeping it as a
standalone script means installing the gRPC stack is opt-in and the
package surface stays slim.
