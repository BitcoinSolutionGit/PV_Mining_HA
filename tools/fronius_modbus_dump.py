from __future__ import annotations

import argparse
import csv
import socket
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_RANGES = (
    ("holding", 40000, 41050),
    ("input", 40000, 41050),
)

MAX_REGISTERS_PER_READ = 125
MODEL_HEADER_LEN = 2


@dataclass
class ReadResult:
    kind: str
    raw_address: int
    register_number: int
    value: int | None
    status: str
    detail: str = ""


class ModbusError(Exception):
    pass


class ModbusExceptionResponse(ModbusError):
    def __init__(self, function_code: int, exception_code: int):
        self.function_code = function_code
        self.exception_code = exception_code
        super().__init__(f"modbus exception fc={function_code} code={exception_code}")


class ModbusTcpClient:
    def __init__(self, host: str, port: int, unit: int, timeout: float):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self._tx_id = 0
        self._sock: socket.socket | None = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def connect(self) -> None:
        self.close()
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _ensure_socket(self) -> socket.socket:
        if self._sock is None:
            self.connect()
        assert self._sock is not None
        return self._sock

    def _next_tx_id(self) -> int:
        self._tx_id = (self._tx_id + 1) & 0xFFFF
        return self._tx_id

    def _recv_exact(self, size: int) -> bytes:
        sock = self._ensure_socket()
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ModbusError("connection closed while receiving")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def read_registers(self, kind: str, raw_address: int, quantity: int) -> list[int]:
        if quantity <= 0 or quantity > MAX_REGISTERS_PER_READ:
            raise ValueError(f"quantity must be 1..{MAX_REGISTERS_PER_READ}")
        fc = 3 if kind == "holding" else 4 if kind == "input" else None
        if fc is None:
            raise ValueError(f"unsupported register kind: {kind}")

        tx_id = self._next_tx_id()
        pdu = struct.pack(">BHH", fc, raw_address, quantity)
        mbap = struct.pack(">HHHB", tx_id, 0, len(pdu) + 1, self.unit)
        packet = mbap + pdu

        try:
            self._ensure_socket().sendall(packet)
            header = self._recv_exact(7)
            rx_tx_id, proto_id, length, unit = struct.unpack(">HHHB", header)
            if rx_tx_id != tx_id:
                raise ModbusError(f"transaction mismatch {rx_tx_id} != {tx_id}")
            if proto_id != 0:
                raise ModbusError(f"unexpected protocol id {proto_id}")
            payload = self._recv_exact(length - 1)
        except (OSError, TimeoutError) as exc:
            self.close()
            raise ModbusError(str(exc)) from exc

        if unit != self.unit:
            raise ModbusError(f"unexpected unit id {unit}")
        if len(payload) < 2:
            raise ModbusError("short modbus payload")

        resp_fc = payload[0]
        if resp_fc == (fc | 0x80):
            raise ModbusExceptionResponse(fc, payload[1] if len(payload) > 1 else -1)
        if resp_fc != fc:
            raise ModbusError(f"unexpected function code {resp_fc}")

        byte_count = payload[1]
        data = payload[2:]
        if len(data) != byte_count:
            raise ModbusError(f"byte-count mismatch {len(data)} != {byte_count}")
        if byte_count != quantity * 2:
            raise ModbusError(f"register-count mismatch {byte_count} != {quantity * 2}")

        return [struct.unpack(">H", data[i : i + 2])[0] for i in range(0, len(data), 2)]


def parse_range_spec(spec: str) -> tuple[str, int, int]:
    try:
        kind_part, addr_part = spec.split(":", 1)
        start_part, end_part = addr_part.split("-", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid range '{spec}', expected holding:40000-41050"
        ) from exc

    kind = kind_part.strip().lower()
    if kind not in ("holding", "input"):
        raise argparse.ArgumentTypeError("range type must be 'holding' or 'input'")
    try:
        start = int(start_part)
        end = int(end_part)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("range addresses must be integers") from exc
    if start < 0 or end < start:
        raise argparse.ArgumentTypeError("range addresses must satisfy 0 <= start <= end")
    return kind, start, end


def scan_range(
    client: ModbusTcpClient,
    kind: str,
    start: int,
    end: int,
    chunk_size: int,
    pause_s: float,
) -> list[ReadResult]:
    results: list[ReadResult] = []
    pos = start
    while pos <= end:
        qty = min(chunk_size, end - pos + 1, MAX_REGISTERS_PER_READ)
        results.extend(_scan_block(client, kind, pos, qty))
        pos += qty
        if pause_s > 0:
            time.sleep(pause_s)
    return results


def read_range_values(
    client: ModbusTcpClient,
    kind: str,
    start: int,
    end: int,
    chunk_size: int,
    pause_s: float,
) -> dict[int, int]:
    rows = scan_range(client, kind, start, end, chunk_size, pause_s)
    return {row.raw_address: int(row.value) for row in rows if row.status == "ok" and row.value is not None}


def find_model_headers(
    values: dict[int, int],
    model_id: int,
    model_len: int | None = None,
) -> list[tuple[int, int]]:
    hits: list[tuple[int, int]] = []
    for raw_address in sorted(values):
        if values.get(raw_address) != model_id:
            continue
        length = values.get(raw_address + 1)
        if length is None:
            continue
        if model_len is not None and length != model_len:
            continue
        hits.append((raw_address, length))
    return hits


def _scan_block(client: ModbusTcpClient, kind: str, raw_address: int, quantity: int) -> list[ReadResult]:
    try:
        values = client.read_registers(kind, raw_address, quantity)
        return [
            ReadResult(
                kind=kind,
                raw_address=(raw_address + idx),
                register_number=(raw_address + idx + 1),
                value=val,
                status="ok",
            )
            for idx, val in enumerate(values)
        ]
    except ModbusExceptionResponse as exc:
        detail = f"fc={exc.function_code} code={exc.exception_code}"
    except ModbusError as exc:
        detail = str(exc)

    if quantity == 1:
        return [
            ReadResult(
                kind=kind,
                raw_address=raw_address,
                register_number=raw_address + 1,
                value=None,
                status="error",
                detail=detail,
            )
        ]

    left_qty = quantity // 2
    right_qty = quantity - left_qty
    return _scan_block(client, kind, raw_address, left_qty) + _scan_block(
        client, kind, raw_address + left_qty, right_qty
    )


def write_dump_csv(path: Path, rows: list[ReadResult], include_errors: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["kind", "raw_address", "register_number", "value", "status", "detail"],
        )
        writer.writeheader()
        for row in rows:
            if row.status != "ok" and not include_errors:
                continue
            writer.writerow(
                {
                    "kind": row.kind,
                    "raw_address": row.raw_address,
                    "register_number": row.register_number,
                    "value": "" if row.value is None else row.value,
                    "status": row.status,
                    "detail": row.detail,
                }
            )


def load_dump_csv(path: Path) -> dict[tuple[str, int], dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        result: dict[tuple[str, int], dict[str, str]] = {}
        for row in reader:
            try:
                key = (str(row.get("kind", "")).strip(), int(row.get("raw_address", "")))
            except ValueError:
                continue
            result[key] = row
        return result


def diff_dumps(before_path: Path, after_path: Path, out_path: Path) -> tuple[int, int]:
    before = load_dump_csv(before_path)
    after = load_dump_csv(after_path)
    keys = sorted(set(before) | set(after))
    changed = 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "kind",
                "raw_address",
                "register_number",
                "before_value",
                "after_value",
                "before_status",
                "after_status",
                "before_detail",
                "after_detail",
            ],
        )
        writer.writeheader()
        for key in keys:
            b = before.get(key)
            a = after.get(key)
            if b == a:
                continue
            changed += 1
            register_number = ""
            if a and a.get("register_number"):
                register_number = a["register_number"]
            elif b and b.get("register_number"):
                register_number = b["register_number"]
            writer.writerow(
                {
                    "kind": key[0],
                    "raw_address": key[1],
                    "register_number": register_number,
                    "before_value": "" if not b else b.get("value", ""),
                    "after_value": "" if not a else a.get("value", ""),
                    "before_status": "" if not b else b.get("status", ""),
                    "after_status": "" if not a else a.get("status", ""),
                    "before_detail": "" if not b else b.get("detail", ""),
                    "after_detail": "" if not a else a.get("detail", ""),
                }
            )
    return len(keys), changed


def stable_diff_dumps(
    baseline_path: Path,
    before_path: Path,
    after_path: Path,
    out_path: Path,
) -> tuple[int, int, int]:
    baseline = load_dump_csv(baseline_path)
    before = load_dump_csv(before_path)
    after = load_dump_csv(after_path)
    keys = sorted(set(baseline) | set(before) | set(after))
    stable_candidates = 0
    changed = 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "kind",
                "raw_address",
                "register_number",
                "baseline_value",
                "before_value",
                "after_value",
                "baseline_status",
                "before_status",
                "after_status",
                "baseline_detail",
                "before_detail",
                "after_detail",
            ],
        )
        writer.writeheader()
        for key in keys:
            b0 = baseline.get(key)
            b1 = before.get(key)
            a = after.get(key)
            if b0 != b1:
                continue
            stable_candidates += 1
            if b1 == a:
                continue
            changed += 1
            register_number = ""
            if a and a.get("register_number"):
                register_number = a["register_number"]
            elif b1 and b1.get("register_number"):
                register_number = b1["register_number"]
            elif b0 and b0.get("register_number"):
                register_number = b0["register_number"]
            writer.writerow(
                {
                    "kind": key[0],
                    "raw_address": key[1],
                    "register_number": register_number,
                    "baseline_value": "" if not b0 else b0.get("value", ""),
                    "before_value": "" if not b1 else b1.get("value", ""),
                    "after_value": "" if not a else a.get("value", ""),
                    "baseline_status": "" if not b0 else b0.get("status", ""),
                    "before_status": "" if not b1 else b1.get("status", ""),
                    "after_status": "" if not a else a.get("status", ""),
                    "baseline_detail": "" if not b0 else b0.get("detail", ""),
                    "before_detail": "" if not b1 else b1.get("detail", ""),
                    "after_detail": "" if not a else a.get("detail", ""),
                }
            )
    return len(keys), stable_candidates, changed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan Fronius Modbus TCP registers and write CSV dumps or diffs."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dump_p = sub.add_parser("dump", help="read registers and write a CSV dump")
    dump_p.add_argument("--host", required=True, help="Modbus TCP host/IP")
    dump_p.add_argument("--port", type=int, default=502, help="Modbus TCP port")
    dump_p.add_argument("--unit", type=int, default=1, help="Modbus unit/slave id")
    dump_p.add_argument(
        "--range",
        dest="ranges",
        action="append",
        type=parse_range_spec,
        help="range spec like holding:40000-41050 or input:40000-41050; repeatable",
    )
    dump_p.add_argument(
        "--chunk-size",
        type=int,
        default=40,
        help=f"preferred registers per request, max {MAX_REGISTERS_PER_READ}",
    )
    dump_p.add_argument("--timeout", type=float, default=3.0, help="socket timeout in seconds")
    dump_p.add_argument("--pause-ms", type=int, default=50, help="pause between requests")
    dump_p.add_argument(
        "--include-errors",
        action="store_true",
        help="also write unreadable addresses into the CSV",
    )
    dump_p.add_argument("--output", required=True, help="target CSV path")

    diff_p = sub.add_parser("diff", help="compare two CSV dumps")
    diff_p.add_argument("--before", required=True, help="older CSV dump")
    diff_p.add_argument("--after", required=True, help="newer CSV dump")
    diff_p.add_argument("--output", required=True, help="target CSV path for changes only")

    stable_diff_p = sub.add_parser(
        "stable-diff",
        help="compare baseline/before/after and keep only stable-then-changed registers",
    )
    stable_diff_p.add_argument("--baseline", required=True, help="baseline no-change CSV dump")
    stable_diff_p.add_argument("--before", required=True, help="second no-change CSV dump")
    stable_diff_p.add_argument("--after", required=True, help="after-change CSV dump")
    stable_diff_p.add_argument("--output", required=True, help="target CSV path for filtered changes")

    locate_p = sub.add_parser("locate-model", help="scan a range and find SunSpec model headers")
    locate_p.add_argument("--host", required=True, help="Modbus TCP host/IP")
    locate_p.add_argument("--port", type=int, default=502, help="Modbus TCP port")
    locate_p.add_argument("--unit", type=int, default=1, help="Modbus unit/slave id")
    locate_p.add_argument("--kind", choices=("holding", "input"), default="holding", help="register kind to scan")
    locate_p.add_argument("--start", type=int, default=40000, help="start raw address")
    locate_p.add_argument("--end", type=int, default=41050, help="end raw address")
    locate_p.add_argument("--model-id", type=int, required=True, help="SunSpec model id to find, e.g. 124")
    locate_p.add_argument("--model-len", type=int, default=None, help="optional expected model length, e.g. 24")
    locate_p.add_argument(
        "--chunk-size",
        type=int,
        default=60,
        help=f"preferred registers per request, max {MAX_REGISTERS_PER_READ}",
    )
    locate_p.add_argument("--timeout", type=float, default=3.0, help="socket timeout in seconds")
    locate_p.add_argument("--pause-ms", type=int, default=50, help="pause between requests")

    dump_model_p = sub.add_parser("dump-model", help="locate a SunSpec model header and dump that exact block")
    dump_model_p.add_argument("--host", required=True, help="Modbus TCP host/IP")
    dump_model_p.add_argument("--port", type=int, default=502, help="Modbus TCP port")
    dump_model_p.add_argument("--unit", type=int, default=1, help="Modbus unit/slave id")
    dump_model_p.add_argument("--kind", choices=("holding", "input"), default="holding", help="register kind to scan")
    dump_model_p.add_argument("--start", type=int, default=40000, help="start raw address for discovery")
    dump_model_p.add_argument("--end", type=int, default=41050, help="end raw address for discovery")
    dump_model_p.add_argument("--model-id", type=int, required=True, help="SunSpec model id to dump, e.g. 124")
    dump_model_p.add_argument("--model-len", type=int, default=None, help="optional expected model length, e.g. 24")
    dump_model_p.add_argument(
        "--chunk-size",
        type=int,
        default=60,
        help=f"preferred registers per request, max {MAX_REGISTERS_PER_READ}",
    )
    dump_model_p.add_argument("--timeout", type=float, default=3.0, help="socket timeout in seconds")
    dump_model_p.add_argument("--pause-ms", type=int, default=50, help="pause between requests")
    dump_model_p.add_argument("--include-errors", action="store_true", help="also write unreadable addresses into the CSV")
    dump_model_p.add_argument("--output", required=True, help="target CSV path")
    dump_model_p.add_argument(
        "--hit-index",
        type=int,
        default=0,
        help="which located hit to use if several candidates are found",
    )

    return parser


def run_dump(args: argparse.Namespace) -> int:
    chunk_size = max(1, min(int(args.chunk_size), MAX_REGISTERS_PER_READ))
    ranges = args.ranges or list(DEFAULT_RANGES)
    all_rows: list[ReadResult] = []
    start_ts = time.time()
    with ModbusTcpClient(args.host, int(args.port), int(args.unit), float(args.timeout)) as client:
        for kind, start, end in ranges:
            print(f"[dump] {kind} {start}-{end}", flush=True)
            rows = scan_range(client, kind, start, end, chunk_size, max(0.0, args.pause_ms / 1000.0))
            ok_count = sum(1 for row in rows if row.status == "ok")
            err_count = len(rows) - ok_count
            print(f"[dump] {kind} {start}-{end} -> ok={ok_count} err={err_count}", flush=True)
            all_rows.extend(rows)

    write_dump_csv(Path(args.output), all_rows, include_errors=bool(args.include_errors))
    elapsed = time.time() - start_ts
    ok_count = sum(1 for row in all_rows if row.status == "ok")
    err_count = len(all_rows) - ok_count
    print(
        f"[dump] wrote {args.output} rows={len(all_rows)} ok={ok_count} err={err_count} elapsed={elapsed:.1f}s",
        flush=True,
    )
    return 0


def run_diff(args: argparse.Namespace) -> int:
    total, changed = diff_dumps(Path(args.before), Path(args.after), Path(args.output))
    print(f"[diff] compared={total} changed={changed} wrote={args.output}", flush=True)
    return 0


def run_stable_diff(args: argparse.Namespace) -> int:
    total, stable_candidates, changed = stable_diff_dumps(
        Path(args.baseline),
        Path(args.before),
        Path(args.after),
        Path(args.output),
    )
    print(
        f"[stable-diff] compared={total} stable_candidates={stable_candidates} changed={changed} wrote={args.output}",
        flush=True,
    )
    return 0


def run_locate_model(args: argparse.Namespace) -> int:
    chunk_size = max(1, min(int(args.chunk_size), MAX_REGISTERS_PER_READ))
    pause_s = max(0.0, args.pause_ms / 1000.0)
    with ModbusTcpClient(args.host, int(args.port), int(args.unit), float(args.timeout)) as client:
        values = read_range_values(client, args.kind, int(args.start), int(args.end), chunk_size, pause_s)
    hits = find_model_headers(values, int(args.model_id), args.model_len)
    if not hits:
        print(
            f"[locate-model] no hits for model_id={args.model_id} len={args.model_len} in {args.kind} {args.start}-{args.end}",
            flush=True,
        )
        return 1
    for idx, (raw_address, model_len) in enumerate(hits):
        print(
            f"[locate-model] hit[{idx}] kind={args.kind} header_raw={raw_address} header_reg={raw_address + 1} "
            f"model_id={args.model_id} model_len={model_len} data_raw={raw_address + MODEL_HEADER_LEN} "
            f"data_reg={raw_address + MODEL_HEADER_LEN + 1} end_raw={raw_address + MODEL_HEADER_LEN + model_len - 1}",
            flush=True,
        )
    return 0


def run_dump_model(args: argparse.Namespace) -> int:
    chunk_size = max(1, min(int(args.chunk_size), MAX_REGISTERS_PER_READ))
    pause_s = max(0.0, args.pause_ms / 1000.0)
    with ModbusTcpClient(args.host, int(args.port), int(args.unit), float(args.timeout)) as client:
        values = read_range_values(client, args.kind, int(args.start), int(args.end), chunk_size, pause_s)
        hits = find_model_headers(values, int(args.model_id), args.model_len)
        if not hits:
            print(
                f"[dump-model] no hits for model_id={args.model_id} len={args.model_len} in {args.kind} {args.start}-{args.end}",
                flush=True,
            )
            return 1
        hit_index = int(args.hit_index)
        if hit_index < 0 or hit_index >= len(hits):
            print(f"[dump-model] hit-index {hit_index} out of range 0..{len(hits)-1}", flush=True)
            return 2
        raw_address, model_len = hits[hit_index]
        model_end = raw_address + MODEL_HEADER_LEN + model_len - 1
        print(
            f"[dump-model] using hit[{hit_index}] kind={args.kind} header_raw={raw_address} "
            f"data_raw={raw_address + MODEL_HEADER_LEN} model_len={model_len} end_raw={model_end}",
            flush=True,
        )
        rows = scan_range(client, args.kind, raw_address, model_end, chunk_size, pause_s)
    write_dump_csv(Path(args.output), rows, include_errors=bool(args.include_errors))
    ok_count = sum(1 for row in rows if row.status == "ok")
    err_count = len(rows) - ok_count
    print(f"[dump-model] wrote {args.output} rows={len(rows)} ok={ok_count} err={err_count}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "dump":
        return run_dump(args)
    if args.command == "diff":
        return run_diff(args)
    if args.command == "stable-diff":
        return run_stable_diff(args)
    if args.command == "locate-model":
        return run_locate_model(args)
    if args.command == "dump-model":
        return run_dump_model(args)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
