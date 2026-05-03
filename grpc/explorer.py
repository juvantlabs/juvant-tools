"""
explorer.py — Interactive gRPC explorer
========================================
Connects to a gRPC server, discovers its services (via server reflection
or by compiling local .proto files), lets you pick a method, prepare a
JSON payload in your editor of choice, invoke the method, and pretty-prints
the response.

Discovery (auto-fallback chain since v0.2):

  1. Try server reflection (`grpc.reflection.v1alpha.ServerReflection`).
  2. If reflection fails (UNIMPLEMENTED, channel error, zero services)
     and `--proto-dir PATH` is supplied, compile every `.proto` under
     PATH with `grpc_tools.protoc` and use the resulting descriptors.
  3. If both fail (or `--proto-dir` not supplied), exit with a clear
     error.

  `--no-reflection` skips step 1 entirely and goes straight to
  proto-dir mode (requires `--proto-dir`). Useful when local .proto
  files are more up-to-date than the server's exposed schema, or when
  the server's reflection cooperates only partially.

Invocation modes (auto-detected):

- **Scripted**: pass `--service`, `--method`, and (`--payload` or
  `--payload-file`) — runs end-to-end without prompts. For streaming
  request methods (client-streaming, bidi-streaming), the payload
  must be a JSON array; each element is one message in the stream.
- **Interactive** (default): walks numbered menus to pick service +
  method, then opens an editor on a JSON template. Requires a TTY.

Editor discovery (git-style fallback chain):

  1. `--editor CMD`              (explicit override)
  2. `$VISUAL`                   (env var)
  3. `$EDITOR`                   (env var)
  4. Platform default            (`notepad` on Windows; `nano` then `vi` on Unix)
  5. File mode                   (`--no-editor`, or auto when no editor found):
                                  prints the tempfile path, waits for Enter

Streaming support (v0.2):

  - unary-unary       ✓
  - server-streaming  ✓ (reads to EOF, prints each message)
  - client-streaming  ✓ (sends every element of the JSON array, then reads one response)
  - bidi-streaming    ✓ (sends every element, then reads to EOF — no interleaving)

Usage:
  # Interactive, with reflection
  python3 grpc/explorer.py --host localhost:50051

  # Interactive, with local .proto files (used as fallback if reflection fails)
  python3 grpc/explorer.py --host api.example.com:443 --tls --proto-dir ./protos

  # Force proto-dir mode (skip reflection)
  python3 grpc/explorer.py --host localhost:50051 --no-reflection --proto-dir ./protos

  # Scripted (unary)
  python3 grpc/explorer.py --host localhost:50051 \\
    --service my.pkg.MyService --method GetThing --payload '{"id":"abc"}'

  # Scripted (client-streaming or bidi — JSON array of messages)
  python3 grpc/explorer.py --host localhost:50051 \\
    --service my.pkg.MyService --method UploadStream \\
    --payload '[{"chunk":"a"},{"chunk":"b"},{"chunk":"c"}]'

  # Auth via per-call metadata
  python3 grpc/explorer.py --host api.example.com:443 --tls \\
    --metadata authorization='Bearer eyJ...'

Dependencies (install separately — not pulled by juvant-tools):
  pip install grpcio grpcio-reflection grpcio-tools protobuf
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import click


# Late import for the gRPC stack — defer until needed so --help works
# without grpcio installed.
def _import_grpc() -> tuple[Any, ...]:
    try:
        import grpc  # noqa: PLC0415
        from google.protobuf import descriptor_pb2, descriptor_pool, message_factory  # noqa: PLC0415
        from google.protobuf.json_format import MessageToJson, Parse, ParseError  # noqa: PLC0415
    except ImportError as exc:
        click.echo(
            "ERROR: gRPC stack not installed.\n"
            "Install with: pip install grpcio grpcio-reflection grpcio-tools protobuf",
            err=True,
        )
        raise SystemExit(1) from exc
    return grpc, descriptor_pb2, descriptor_pool, message_factory, MessageToJson, Parse, ParseError


# =====================================================================
# Connection
# =====================================================================

def build_channel(
    host_port: str,
    tls: bool,
    ca_cert: Path | None,
    client_cert: Path | None,
    client_key: Path | None,
):
    """Open a gRPC channel — insecure, TLS, or mTLS depending on flags."""
    grpc, *_ = _import_grpc()
    if not tls:
        return grpc.insecure_channel(host_port)

    root_certs = ca_cert.read_bytes() if ca_cert else None
    private_key = client_key.read_bytes() if client_key else None
    cert_chain = client_cert.read_bytes() if client_cert else None
    creds = grpc.ssl_channel_credentials(
        root_certificates=root_certs,
        private_key=private_key,
        certificate_chain=cert_chain,
    )
    return grpc.secure_channel(host_port, creds)


def parse_metadata(items: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Parse repeated --metadata KEY=VAL flags into a tuple of pairs."""
    out: list[tuple[str, str]] = []
    for item in items:
        if "=" not in item:
            raise click.BadParameter(
                f"--metadata expects KEY=VAL, got {item!r}",
                param_hint="--metadata",
            )
        key, val = item.split("=", 1)
        out.append((key.strip().lower(), val))
    return tuple(out)


# =====================================================================
# Reflection mode
# =====================================================================

REFLECTION_SERVICE_NAME = "grpc.reflection.v1alpha.ServerReflection"


def reflection_query(stub, request):
    """Send a single ServerReflectionRequest and return the single response.

    The reflection service is bidi-streaming, but each logical query is a
    one-shot send/recv/close.
    """
    responses = stub.ServerReflectionInfo(iter([request]))
    return next(responses)


def reflection_list_services(stub) -> list[str]:
    from grpc_reflection.v1alpha import reflection_pb2  # noqa: PLC0415

    req = reflection_pb2.ServerReflectionRequest(list_services="")
    resp = reflection_query(stub, req)
    return [
        s.name for s in resp.list_services_response.service
        if s.name != REFLECTION_SERVICE_NAME
    ]


def reflection_fetch_descriptors(stub, root_service: str) -> dict[str, Any]:
    """Recursively fetch every FileDescriptorProto needed for root_service.

    Returns a dict file_name → FileDescriptorProto.
    """
    grpc, descriptor_pb2, *_ = _import_grpc()
    from grpc_reflection.v1alpha import reflection_pb2  # noqa: PLC0415

    files: dict[str, Any] = {}

    def parse_response(resp) -> None:
        for fd_bytes in resp.file_descriptor_response.file_descriptor_proto:
            fd_proto = descriptor_pb2.FileDescriptorProto()
            fd_proto.ParseFromString(fd_bytes)
            if fd_proto.name not in files:
                files[fd_proto.name] = fd_proto
                for dep in fd_proto.dependency:
                    fetch_by_name(dep)

    def fetch_by_symbol(symbol: str) -> None:
        try:
            req = reflection_pb2.ServerReflectionRequest(file_containing_symbol=symbol)
            resp = reflection_query(stub, req)
            parse_response(resp)
        except grpc.RpcError as e:
            click.echo(f"[!] Reflection: could not fetch descriptor for symbol {symbol}: {e.code()}", err=True)

    def fetch_by_name(name: str) -> None:
        if name in files:
            return
        try:
            req = reflection_pb2.ServerReflectionRequest(file_by_filename=name)
            resp = reflection_query(stub, req)
            parse_response(resp)
        except grpc.RpcError:
            # Standard protos (google/protobuf/*.proto) sometimes aren't served
            # by reflection but are bundled with the protobuf library — copy
            # from the default pool below.
            pass

    fetch_by_symbol(root_service)
    return files


def build_pool_from_descriptors(files: dict[str, Any]):
    """Build a fresh DescriptorPool with files added in topological order.

    For dependencies missing from `files` (e.g. google/protobuf well-known
    types not served by reflection), copy from the default pool as fallback.
    """
    grpc, descriptor_pb2, descriptor_pool, *_ = _import_grpc()

    pool = descriptor_pool.DescriptorPool()
    added: set[str] = set()

    def add(name: str) -> None:
        if name in added:
            return
        fd = files.get(name)
        if fd is None:
            # Try the default pool — well-known protos live there
            try:
                default_fd = descriptor_pool.Default().FindFileByName(name)
                fd_proto = descriptor_pb2.FileDescriptorProto()
                default_fd.CopyToProto(fd_proto)
                files[name] = fd_proto
                fd = fd_proto
            except KeyError:
                click.echo(f"[!] Missing dependency {name} — skipping", err=True)
                return

        for dep in fd.dependency:
            add(dep)

        try:
            pool.Add(fd)
        except TypeError:
            pass  # already in pool via another path
        added.add(name)

    for name in list(files.keys()):
        add(name)

    return pool


# =====================================================================
# Proto-dir mode
# =====================================================================

def compile_protos(proto_dir: Path) -> tuple[Any, list[str]]:
    """Run `python -m grpc_tools.protoc` on every .proto under proto_dir,
    output to a tempdir, and import the generated `_pb2.py` modules so
    their descriptors register in the default pool.

    Returns (pool, services) — the default pool plus a list of every
    service full-name found across the imported FileDescriptors.
    """
    _import_grpc()  # ensure deps available

    proto_files = list(proto_dir.rglob("*.proto"))
    if not proto_files:
        raise click.ClickException(f"No .proto files found under {proto_dir}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="grpc-explorer-"))
    cmd = [
        sys.executable, "-m", "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"--python_out={tmp_dir}",
        *[str(p) for p in proto_files],
    ]
    click.echo(f"[*] Compiling {len(proto_files)} .proto file(s) to {tmp_dir}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        click.echo(result.stderr, err=True)
        raise click.ClickException("protoc failed")

    # Import generated modules so descriptors register in the default pool.
    # Collect service full-names from each file's DESCRIPTOR.
    sys.path.insert(0, str(tmp_dir))
    services: list[str] = []
    for py_file in tmp_dir.rglob("*_pb2.py"):
        module_name = py_file.relative_to(tmp_dir).with_suffix("").as_posix().replace("/", ".")
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as e:  # noqa: BLE001
                click.echo(f"[!] Failed to import {module_name}: {e}", err=True)
                continue
            file_desc = getattr(module, "DESCRIPTOR", None)
            if file_desc is not None:
                for svc in file_desc.services_by_name.values():
                    if svc.full_name not in services:
                        services.append(svc.full_name)

    from google.protobuf import descriptor_pool as dp  # noqa: PLC0415
    return dp.Default(), services


# =====================================================================
# Service / method introspection
# =====================================================================

def list_methods(pool, service_full_name: str) -> list[str]:
    service_desc = pool.FindServiceByName(service_full_name)
    return [m.name for m in service_desc.methods]


def method_descriptor(pool, service_full_name: str, method_name: str):
    service_desc = pool.FindServiceByName(service_full_name)
    return service_desc.FindMethodByName(method_name)


def method_full_path(service_full_name: str, method_name: str) -> str:
    return f"/{service_full_name}/{method_name}"


def method_kind(method_desc) -> str:
    """Return one of: unary-unary, server-streaming, client-streaming, bidi-streaming."""
    if method_desc.client_streaming and method_desc.server_streaming:
        return "bidi-streaming"
    if method_desc.client_streaming:
        return "client-streaming"
    if method_desc.server_streaming:
        return "server-streaming"
    return "unary-unary"


def method_signature_str(method_desc) -> str:
    """Return a one-liner like 'unary-unary  Request → Response'."""
    return f"{method_kind(method_desc):18}  {method_desc.input_type.full_name}  →  {method_desc.output_type.full_name}"


# =====================================================================
# Message construction + JSON template
# =====================================================================

def message_class_for(pool, type_full_name: str):
    _, _, _, message_factory, _, _, _ = _import_grpc()
    descriptor = pool.FindMessageTypeByName(type_full_name)
    factory = message_factory.MessageFactory(pool=pool)
    # Newer protobuf: GetMessageClass(descriptor); older: GetPrototype(descriptor)
    if hasattr(message_factory, "GetMessageClass"):
        return message_factory.GetMessageClass(descriptor)
    return factory.GetPrototype(descriptor)


def build_template_dict(descriptor, pool, depth: int = 0, max_depth: int = 4) -> dict:
    """Walk a message descriptor and produce a dict with default zero values
    for every field. Recurses into nested messages up to max_depth."""
    template: dict[str, Any] = {}
    for field in descriptor.fields:
        template[field.name] = _default_for_field(field, pool, depth, max_depth)
    return template


def _default_for_field(field, pool, depth: int, max_depth: int) -> Any:
    LABEL_REPEATED = 3  # field.LABEL_REPEATED
    if field.label == LABEL_REPEATED:
        return []

    # https://protobuf.dev/programming-guides/proto3/#scalar
    TYPE_DOUBLE   = 1
    TYPE_FLOAT    = 2
    TYPE_INT64    = 3
    TYPE_UINT64   = 4
    TYPE_INT32    = 5
    TYPE_FIXED64  = 6
    TYPE_FIXED32  = 7
    TYPE_BOOL     = 8
    TYPE_STRING   = 9
    TYPE_GROUP    = 10
    TYPE_MESSAGE  = 11
    TYPE_BYTES    = 12
    TYPE_UINT32   = 13
    TYPE_ENUM     = 14
    TYPE_SFIXED32 = 15
    TYPE_SFIXED64 = 16
    TYPE_SINT32   = 17
    TYPE_SINT64   = 18

    t = field.type
    if t in (TYPE_INT32, TYPE_INT64, TYPE_UINT32, TYPE_UINT64,
             TYPE_FIXED32, TYPE_FIXED64, TYPE_SFIXED32, TYPE_SFIXED64,
             TYPE_SINT32, TYPE_SINT64):
        return 0
    if t in (TYPE_FLOAT, TYPE_DOUBLE):
        return 0.0
    if t == TYPE_BOOL:
        return False
    if t == TYPE_STRING:
        return ""
    if t == TYPE_BYTES:
        return ""  # base64 in proto-JSON
    if t == TYPE_ENUM:
        if field.enum_type.values:
            return field.enum_type.values[0].name
        return ""
    if t in (TYPE_MESSAGE, TYPE_GROUP):
        if depth >= max_depth:
            return {"_truncated": f"max nesting depth {max_depth} reached"}
        return build_template_dict(field.message_type, pool, depth + 1, max_depth)
    return None


# =====================================================================
# Editor + payload UX
# =====================================================================

def discover_editor(override: str | None) -> tuple[list[str] | None, str | None]:
    """Return (cmd_argv, hint).
    - cmd_argv: list of arguments to spawn the editor (None → file mode)
    - hint:     short message about how to save+exit (None → no hint)
    """
    if override:
        return shlex.split(override), None

    for var in ("VISUAL", "EDITOR"):
        cmd = os.environ.get(var)
        if cmd:
            return shlex.split(cmd), None

    if platform.system() == "Windows":
        if shutil.which("notepad"):
            return ["notepad"], "Save (Ctrl+S) and close the window to continue."
        return None, None

    for cmd, hint in (
        ("nano", "Press Ctrl+X then Y then Enter to save and continue."),
        ("vi",   "Press Esc, then type :wq and Enter to save and continue."),
    ):
        if shutil.which(cmd):
            return [cmd], hint
    return None, None


def edit_payload_in_editor(template_json: str, override: str | None, no_editor: bool) -> str:
    """Open an editor (or fallback to file-mode prompt) on a tempfile pre-filled
    with template_json. Return the contents after the user is done."""
    fd, tmp_path_str = tempfile.mkstemp(prefix="grpc-payload-", suffix=".json")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(template_json)

        if no_editor:
            cmd, hint = None, None
        else:
            cmd, hint = discover_editor(override)

        if cmd is None:
            click.echo("")
            if not no_editor:
                click.echo("[*] No editor found in PATH (tried nano, vi). Falling back to file mode.")
            click.echo(f"[*] Edit this file in your editor of choice, then press Enter:")
            click.echo(f"[*]   {tmp_path}")
            input()
        else:
            click.echo("")
            click.echo(f"[*] Launching editor: {' '.join(cmd)}")
            if hint:
                click.echo(f"[*] {hint}")
            click.echo("")
            try:
                subprocess.run(cmd + [str(tmp_path)], check=True)
            except subprocess.CalledProcessError as e:
                raise click.ClickException(f"Editor exited with status {e.returncode}") from e

        return tmp_path.read_text(encoding="utf-8")
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


# =====================================================================
# Invocation
# =====================================================================

def invoke(
    channel,
    method_full_path_str: str,
    request_msgs: list,
    response_class,
    metadata: tuple[tuple[str, str], ...],
    kind: str,
):
    """Invoke a method according to its kind. Returns a response message
    (unary-unary, client-streaming) or an iterator of messages
    (server-streaming, bidi-streaming).

    request_msgs is always a list of request messages:
      - unary-unary / server-streaming → list of length 1, only [0] is sent
      - client-streaming / bidi-streaming → all elements are sent in order

    For bidi, this implementation sends all requests first (no interleaving),
    then reads responses to EOF. Adequate for an exploration tool; not a
    full bidi simulator.
    """
    serializer = lambda m: m.SerializeToString()  # noqa: E731
    deserializer = lambda d: response_class.FromString(d)  # noqa: E731

    if kind == "unary-unary":
        rpc = channel.unary_unary(method_full_path_str, request_serializer=serializer, response_deserializer=deserializer)
        return rpc(request_msgs[0], metadata=metadata)
    if kind == "server-streaming":
        rpc = channel.unary_stream(method_full_path_str, request_serializer=serializer, response_deserializer=deserializer)
        return rpc(request_msgs[0], metadata=metadata)
    if kind == "client-streaming":
        rpc = channel.stream_unary(method_full_path_str, request_serializer=serializer, response_deserializer=deserializer)
        return rpc(iter(request_msgs), metadata=metadata)
    if kind == "bidi-streaming":
        rpc = channel.stream_stream(method_full_path_str, request_serializer=serializer, response_deserializer=deserializer)
        return rpc(iter(request_msgs), metadata=metadata)
    raise click.ClickException(f"Unknown method kind: {kind}")


def render_response(resp, kind: str) -> None:
    _, _, _, _, MessageToJson, _, _ = _import_grpc()

    def render_one(msg) -> None:
        click.echo(MessageToJson(msg, preserving_proto_field_name=True))

    click.echo("")
    click.echo("=== Response ===")
    is_streaming_response = kind in ("server-streaming", "bidi-streaming")
    if is_streaming_response:
        count = 0
        try:
            for msg in resp:
                count += 1
                click.echo(f"--- Message #{count} ---")
                render_one(msg)
        finally:
            click.echo(f"--- End of stream ({count} message{'s' if count != 1 else ''}) ---")
    else:
        render_one(resp)


def parse_payload_to_msgs(payload_str: str, request_class, request_streaming: bool) -> list:
    """Parse a JSON payload into a list of request messages.

    For streaming requests, expect a JSON array; each element becomes one
    request message. For unary requests, expect a JSON object.
    """
    _, _, _, _, _, Parse, ParseError = _import_grpc()

    if request_streaming:
        try:
            arr = json.loads(payload_str)
        except json.JSONDecodeError as e:
            raise click.ClickException(
                f"Streaming request expects a JSON array of messages; payload is not valid JSON: {e}"
            ) from e
        if not isinstance(arr, list):
            raise click.ClickException(
                f"Streaming request expects a JSON array; got {type(arr).__name__}. "
                "Each array element should be one request message."
            )
        if not arr:
            raise click.ClickException(
                "Streaming request payload is an empty array — at least one message required."
            )
        msgs = []
        for i, elem in enumerate(arr):
            try:
                msg = Parse(json.dumps(elem), request_class(), ignore_unknown_fields=False)
            except ParseError as e:
                raise click.ClickException(
                    f"Invalid JSON for stream message #{i+1} of {request_class.DESCRIPTOR.full_name}: {e}"
                ) from e
            msgs.append(msg)
        return msgs

    # Unary request — payload must be a JSON object, not an array
    try:
        parsed = json.loads(payload_str)
    except json.JSONDecodeError as e:
        raise click.ClickException(
            f"Invalid JSON payload for {request_class.DESCRIPTOR.full_name}: {e}"
        ) from e
    if isinstance(parsed, list):
        raise click.ClickException(
            f"Unary-request method expects a JSON object; got an array. "
            f"Drop the outer brackets or check that you're invoking the right method."
        )
    try:
        return [Parse(payload_str, request_class(), ignore_unknown_fields=False)]
    except ParseError as e:
        raise click.ClickException(
            f"Invalid JSON payload for {request_class.DESCRIPTOR.full_name}: {e}"
        ) from e


def build_payload_template_json(m_desc, pool) -> tuple[str, str]:
    """Return (template_json, hint) — the JSON template to seed the editor
    with, plus a one-line hint about format expectations."""
    msg_template = build_template_dict(m_desc.input_type, pool)
    if m_desc.client_streaming:
        # JSON array of messages — start with a single default message
        return (
            json.dumps([msg_template], indent=2),
            "Streaming-request method: payload is a JSON ARRAY. Add more elements for additional stream messages.",
        )
    return (json.dumps(msg_template, indent=2), "")


# =====================================================================
# Interactive flow
# =====================================================================

def pick_from_menu(items: list[str], prompt: str) -> str:
    if not items:
        raise click.ClickException(f"{prompt}: empty list — nothing to pick")
    click.echo("")
    for i, item in enumerate(items, start=1):
        click.echo(f"  [{i}] {item}")
    idx = click.prompt(prompt, type=click.IntRange(1, len(items)))
    return items[idx - 1]


def interactive_flow(
    channel,
    pool,
    services: list[str],
    metadata: tuple[tuple[str, str], ...],
    editor_override: str | None,
    no_editor: bool,
) -> None:
    if not sys.stdin.isatty():
        raise click.ClickException(
            "Interactive mode requires a TTY. Use --service/--method/--payload "
            "(or --payload-file) for scripted mode."
        )

    while True:
        # --- Pick service ---
        click.echo("\n[*] Available services:")
        service = pick_from_menu(sorted(services), "Pick a service")

        # --- Pick method ---
        methods = list_methods(pool, service)
        click.echo(f"\n[*] Methods in {service}:")
        method = pick_from_menu(methods, "Pick a method")

        # --- Show signature ---
        m_desc = method_descriptor(pool, service, method)
        click.echo(f"\n[*] Method signature:")
        click.echo(f"      {method_signature_str(m_desc)}")

        # --- Edit payload ---
        template_json, hint = build_payload_template_json(m_desc, pool)
        click.echo(f"\n[*] Request type: {m_desc.input_type.full_name}")
        if hint:
            click.echo(f"[*] {hint}")
        click.echo("[*] Opening editor with a pre-filled JSON template…")
        payload_str = edit_payload_in_editor(template_json, editor_override, no_editor)

        # --- Invoke ---
        try:
            execute_invocation(
                channel=channel,
                pool=pool,
                service=service,
                method=method,
                payload_str=payload_str,
                metadata=metadata,
            )
        except click.ClickException as e:
            click.echo(f"\n[!] {e.format_message()}", err=True)

        if not click.confirm("\nInvoke another method?", default=False):
            return


# =====================================================================
# Scripted flow
# =====================================================================

def execute_invocation(
    channel,
    pool,
    service: str,
    method: str,
    payload_str: str,
    metadata: tuple[tuple[str, str], ...],
) -> None:
    grpc, *_ = _import_grpc()

    try:
        m_desc = method_descriptor(pool, service, method)
    except KeyError as e:
        raise click.ClickException(
            f"Service or method not found: {e.args[0] if e.args else service+'/'+method}"
        ) from e
    if m_desc is None:
        raise click.ClickException(f"Method {method} not found on service {service}")

    kind = method_kind(m_desc)
    request_class = message_class_for(pool, m_desc.input_type.full_name)
    response_class = message_class_for(pool, m_desc.output_type.full_name)
    request_msgs = parse_payload_to_msgs(payload_str, request_class, m_desc.client_streaming)

    full_path = method_full_path(service, method)
    click.echo(f"\n[*] Invoking {full_path}  [{kind}]")
    if m_desc.client_streaming:
        click.echo(f"[*] Sending {len(request_msgs)} request message(s).")
    try:
        resp = invoke(
            channel=channel,
            method_full_path_str=full_path,
            request_msgs=request_msgs,
            response_class=response_class,
            metadata=metadata,
            kind=kind,
        )
        render_response(resp, kind)
    except grpc.RpcError as e:
        click.echo(f"\n[!] RPC failed: {e.code()} — {e.details()}", err=True)
        raise SystemExit(1) from e


# =====================================================================
# Discovery orchestrator (auto-fallback reflection → proto-dir, since v0.2)
# =====================================================================

def _try_reflection(channel) -> tuple[Any | None, list[str] | None, str | None]:
    """Try to discover services via reflection.

    Returns:
      (pool, services, None)         on success
      (None,  None,     reason)      on failure (caller decides whether to fall back)
    """
    grpc, *_ = _import_grpc()
    from grpc_reflection.v1alpha import reflection_pb2_grpc  # noqa: PLC0415

    stub = reflection_pb2_grpc.ServerReflectionStub(channel)
    try:
        services = reflection_list_services(stub)
    except grpc.RpcError as e:
        return None, None, f"{e.code().name}: {e.details() or '(no details)'}"
    except Exception as e:  # noqa: BLE001
        return None, None, f"{type(e).__name__}: {e}"

    if not services:
        return None, None, "reflection returned zero services"

    all_files: dict[str, Any] = {}
    for svc in services:
        all_files.update(reflection_fetch_descriptors(stub, svc))
    pool = build_pool_from_descriptors(all_files)
    return pool, services, None


def discover(
    channel,
    proto_dir: Path | None,
    no_reflection: bool,
) -> tuple[Any, list[str]]:
    """Auto-fallback discovery: reflection first, proto-dir if needed.

    --no-reflection skips step 1 entirely. Requires --proto-dir in that case.
    """
    if no_reflection:
        if proto_dir is None:
            raise click.UsageError("--no-reflection requires --proto-dir PATH")
        click.echo(f"[*] Discovery: proto-dir mode ({proto_dir})  [reflection skipped]")
        return compile_protos(proto_dir)

    click.echo("[*] Discovery: trying reflection…")
    pool, services, fail_reason = _try_reflection(channel)
    if pool is not None and services is not None:
        click.echo("[*] Discovery: reflection succeeded.")
        return pool, services

    # Reflection failed — fall back to proto-dir if available
    if proto_dir is not None:
        click.echo(f"[!] Reflection unavailable ({fail_reason}); falling back to proto-dir mode.")
        click.echo(f"[*] Discovery: proto-dir mode ({proto_dir})")
        return compile_protos(proto_dir)

    raise click.ClickException(
        f"Reflection unavailable ({fail_reason}) and no --proto-dir PATH supplied.\n"
        "Either enable reflection on the server, or pass --proto-dir to compile "
        "local .proto files instead."
    )


# =====================================================================
# CLI
# =====================================================================

@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--host", required=True, metavar="HOST:PORT",
              help="gRPC server endpoint, e.g. localhost:50051 or api.example.com:443.")
@click.option("--tls", is_flag=True, default=False,
              help="Use TLS (default: insecure).")
@click.option("--ca-cert", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to a custom CA certificate (PEM).")
@click.option("--client-cert", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to client certificate for mTLS (PEM).")
@click.option("--client-key", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to client private key for mTLS (PEM).")
@click.option("--metadata", "metadata_items", multiple=True, metavar="KEY=VAL",
              help="Per-call metadata header (repeatable). Example: --metadata authorization='Bearer …'.")
@click.option("--proto-dir", type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Compile .proto files in this directory. Used as fallback when reflection fails, "
                   "or as the sole source when --no-reflection is set.")
@click.option("--no-reflection", is_flag=True, default=False,
              help="Skip server reflection entirely; require --proto-dir.")
@click.option("--service", metavar="FULL_NAME",
              help="Service full name (e.g. my.pkg.MyService). Required for scripted mode.")
@click.option("--method", metavar="NAME",
              help="Method name (e.g. GetThing). Required for scripted mode.")
@click.option("--payload", metavar="JSON",
              help="Inline JSON payload for scripted mode (mutually exclusive with --payload-file).")
@click.option("--payload-file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="JSON payload file for scripted mode (mutually exclusive with --payload).")
@click.option("--editor", metavar="CMD",
              help="Editor command for interactive payload editing (overrides $VISUAL / $EDITOR).")
@click.option("--no-editor", is_flag=True, default=False,
              help="Don't launch an editor; print the tempfile path and wait for Enter.")
def main(
    host: str,
    tls: bool,
    ca_cert: Path | None,
    client_cert: Path | None,
    client_key: Path | None,
    metadata_items: tuple[str, ...],
    proto_dir: Path | None,
    no_reflection: bool,
    service: str | None,
    method: str | None,
    payload: str | None,
    payload_file: Path | None,
    editor: str | None,
    no_editor: bool,
) -> None:
    """Interactive gRPC explorer with reflection / .proto-dir discovery."""
    if payload and payload_file:
        raise click.UsageError("--payload and --payload-file are mutually exclusive")

    metadata = parse_metadata(metadata_items)

    # --- Open channel ---
    channel = build_channel(host, tls, ca_cert, client_cert, client_key)
    click.echo(f"[*] Connected to {host} ({'TLS' if tls else 'insecure'})")

    # --- Discover services (auto-fallback) ---
    pool, services = discover(channel, proto_dir, no_reflection)
    if not services:
        raise click.ClickException("No services discovered.")
    click.echo(f"[*] Discovered {len(services)} service(s).")

    # --- Mode selection: scripted if all required pieces present, else interactive ---
    payload_provided = payload is not None or payload_file is not None
    if service and method and payload_provided:
        if payload is not None:
            payload_str = payload
        else:
            assert payload_file is not None
            payload_str = payload_file.read_text(encoding="utf-8")
        execute_invocation(
            channel=channel,
            pool=pool,
            service=service,
            method=method,
            payload_str=payload_str,
            metadata=metadata,
        )
        return

    interactive_flow(
        channel=channel,
        pool=pool,
        services=services,
        metadata=metadata,
        editor_override=editor,
        no_editor=no_editor,
    )


if __name__ == "__main__":
    main()
