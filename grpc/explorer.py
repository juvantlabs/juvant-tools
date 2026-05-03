"""
explorer.py — Interactive gRPC explorer
========================================
Connects to a gRPC server, discovers its services (via server reflection
or by compiling local .proto files), lets you pick a method, prepare a
JSON payload in your editor of choice, invoke the method, and pretty-prints
the response.

Two discovery modes:

- **Reflection** (default): if the server exposes the
  `grpc.reflection.v1alpha.ServerReflection` service, discover services +
  fetch their `FileDescriptorProto` over the wire.
- **Proto-dir** (fallback): pass `--proto-dir PATH` to compile every
  `.proto` under that directory locally with `grpc_tools.protoc`, then
  use the resulting descriptors. Required for servers with reflection
  disabled.

Two invocation modes (auto-detected):

- **Scripted**: pass `--service`, `--method`, and (`--payload` or
  `--payload-file`) — runs end-to-end without prompts.
- **Interactive** (default): walks numbered menus to pick service +
  method, then opens an editor on a JSON template. Requires a TTY.

Editor discovery (git-style fallback chain):

  1. `--editor CMD`              (explicit override)
  2. `$VISUAL`                   (env var)
  3. `$EDITOR`                   (env var)
  4. Platform default            (`notepad` on Windows; `nano` then `vi` on Unix)
  5. File mode                   (`--no-editor`, or auto when no editor found):
                                  prints the tempfile path, waits for Enter

Streaming support (v0.1):
  - unary-unary       ✓
  - server-streaming  ✓
  - client-streaming  not yet (v0.2)
  - bidi-streaming    not yet (v0.2)

Usage:
  # Interactive, with reflection
  python3 grpc/explorer.py --host localhost:50051

  # Interactive, with local .proto files
  python3 grpc/explorer.py --host api.example.com:443 --tls --proto-dir ./protos

  # Scripted
  python3 grpc/explorer.py --host localhost:50051 \\
    --service my.pkg.MyService --method GetThing --payload '{"id":"abc"}'

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


def method_signature_str(method_desc) -> str:
    """Return a one-liner like 'unary-unary  Request → Response'."""
    if method_desc.client_streaming and method_desc.server_streaming:
        kind = "bidi-streaming"
    elif method_desc.client_streaming:
        kind = "client-streaming"
    elif method_desc.server_streaming:
        kind = "server-streaming"
    else:
        kind = "unary-unary"
    return f"{kind:18}  {method_desc.input_type.full_name}  →  {method_desc.output_type.full_name}"


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
    request_msg,
    response_class,
    metadata: tuple[tuple[str, str], ...],
    server_streaming: bool,
):
    """Invoke a unary-unary or unary-server-streaming method.
    Returns either a single response message or an iterator of messages."""
    serializer = lambda m: m.SerializeToString()  # noqa: E731
    deserializer = lambda d: response_class.FromString(d)  # noqa: E731

    if server_streaming:
        rpc = channel.unary_stream(
            method_full_path_str,
            request_serializer=serializer,
            response_deserializer=deserializer,
        )
    else:
        rpc = channel.unary_unary(
            method_full_path_str,
            request_serializer=serializer,
            response_deserializer=deserializer,
        )
    return rpc(request_msg, metadata=metadata)


def render_response(resp, server_streaming: bool) -> None:
    _, _, _, _, MessageToJson, _, _ = _import_grpc()

    def render_one(msg) -> None:
        click.echo(MessageToJson(msg, preserving_proto_field_name=True))

    click.echo("")
    click.echo("=== Response ===")
    if server_streaming:
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

        if m_desc.client_streaming:
            click.echo(
                "\n[!] Client-streaming and bidi-streaming methods are not supported in v0.1.\n"
                "    Pick another method or invoke this one via grpcurl."
            )
            if not click.confirm("\nPick another method?", default=True):
                return
            continue

        # --- Edit payload ---
        template_dict = build_template_dict(m_desc.input_type, pool)
        template_json = json.dumps(template_dict, indent=2)
        click.echo(f"\n[*] Request type: {m_desc.input_type.full_name}")
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
    grpc, _, _, _, _, Parse, ParseError = _import_grpc()

    try:
        m_desc = method_descriptor(pool, service, method)
    except KeyError as e:
        raise click.ClickException(
            f"Service or method not found: {e.args[0] if e.args else service+'/'+method}"
        ) from e
    if m_desc is None:
        raise click.ClickException(f"Method {method} not found on service {service}")

    if m_desc.client_streaming:
        raise click.ClickException(
            "Client-streaming and bidi-streaming methods are not supported in v0.1."
        )

    request_class = message_class_for(pool, m_desc.input_type.full_name)
    response_class = message_class_for(pool, m_desc.output_type.full_name)

    try:
        request_msg = Parse(payload_str, request_class(), ignore_unknown_fields=False)
    except ParseError as e:
        raise click.ClickException(f"Invalid JSON payload for {m_desc.input_type.full_name}: {e}") from e

    full_path = method_full_path(service, method)
    click.echo(f"\n[*] Invoking {full_path}")
    try:
        resp = invoke(
            channel=channel,
            method_full_path_str=full_path,
            request_msg=request_msg,
            response_class=response_class,
            metadata=metadata,
            server_streaming=m_desc.server_streaming,
        )
        render_response(resp, m_desc.server_streaming)
    except grpc.RpcError as e:
        click.echo(f"\n[!] RPC failed: {e.code()} — {e.details()}", err=True)
        raise SystemExit(1) from e


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
              help="Compile .proto files in this directory instead of using server reflection.")
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
    service: str | None,
    method: str | None,
    payload: str | None,
    payload_file: Path | None,
    editor: str | None,
    no_editor: bool,
) -> None:
    """Interactive gRPC explorer with reflection or .proto-dir discovery."""
    if payload and payload_file:
        raise click.UsageError("--payload and --payload-file are mutually exclusive")

    metadata = parse_metadata(metadata_items)

    # --- Open channel ---
    channel = build_channel(host, tls, ca_cert, client_cert, client_key)
    click.echo(f"[*] Connected to {host} ({'TLS' if tls else 'insecure'})")

    # --- Discover services ---
    if proto_dir is not None:
        click.echo(f"[*] Discovery: proto-dir mode ({proto_dir})")
        pool, services = compile_protos(proto_dir)
        if not services:
            raise click.ClickException(
                f"No services found in {proto_dir}. Make sure your .proto files "
                "define at least one `service { ... }`."
            )
    else:
        click.echo("[*] Discovery: reflection mode")
        from grpc_reflection.v1alpha import reflection_pb2_grpc  # noqa: PLC0415

        stub = reflection_pb2_grpc.ServerReflectionStub(channel)
        try:
            services = reflection_list_services(stub)
        except Exception as e:  # noqa: BLE001
            raise click.ClickException(
                f"Reflection failed: {e}\n"
                "If the server has reflection disabled, supply --proto-dir PATH "
                "to compile local .proto files instead."
            ) from e

        if not services:
            raise click.ClickException("Reflection returned zero services. Server has no exposed services?")

        # Build a unified pool from all reflected services
        all_files: dict[str, Any] = {}
        for svc in services:
            files = reflection_fetch_descriptors(stub, svc)
            all_files.update(files)
        pool = build_pool_from_descriptors(all_files)

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
