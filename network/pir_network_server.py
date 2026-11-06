#!/usr/bin/env python3
"""TCP transport wrapper for Member A's XOR/LWE PIR split APIs."""
import argparse
import json
import socket
import struct
from pathlib import Path

import numpy as np
from pir_core import XorPIRServer, LwePIRServer, LweParams

MAX_HEADER = 1 << 20
MAX_PAYLOAD = 1 << 31


def recv_exact(sock, n):
    chunks = []
    while n:
        b = sock.recv(n)
        if not b:
            raise ConnectionError("peer closed connection early")
        chunks.append(b)
        n -= len(b)
    return b"".join(chunks)


def recv_msg(sock):
    hlen = struct.unpack("!I", recv_exact(sock, 4))[0]
    if hlen <= 0 or hlen > MAX_HEADER:
        raise ValueError("invalid header length")
    header = json.loads(recv_exact(sock, hlen).decode("utf-8"))
    nbytes = int(header.get("nbytes", 0))
    if nbytes < 0 or nbytes > MAX_PAYLOAD:
        raise ValueError("invalid payload size")
    payload = recv_exact(sock, nbytes) if nbytes else b""
    return header, payload


def send_msg(sock, header, array=None):
    payload = b""
    header = dict(header)
    if array is not None:
        array = np.ascontiguousarray(array)
        payload = array.tobytes(order="C")
        header.update(dtype=array.dtype.str, shape=list(array.shape), nbytes=len(payload))
    else:
        header["nbytes"] = 0
    h = json.dumps(header, separators=(",", ":")).encode("utf-8")
    sock.sendall(struct.pack("!I", len(h)) + h + payload)


def array_from(header, payload, expected_dtype):
    if header.get("dtype") != np.dtype(expected_dtype).str:
        raise ValueError("unexpected array dtype")
    shape = tuple(int(x) for x in header.get("shape", []))
    if not shape or any(x < 0 for x in shape):
        raise ValueError("invalid array shape")
    expected = int(np.prod(shape, dtype=np.int64)) * np.dtype(expected_dtype).itemsize
    if expected != len(payload):
        raise ValueError("array shape/payload length mismatch")
    return np.frombuffer(payload, dtype=expected_dtype).reshape(shape).copy()


def load_records(folder):
    folder = Path(folder)
    files = []
    i = 0
    while (folder / f"chunk_{i}.bin").is_file():
        files.append(folder / f"chunk_{i}.bin")
        i += 1
    if not files:
        raise FileNotFoundError(f"No sequential chunk_0.bin, chunk_1.bin, ... files in {folder}")
    data = [p.read_bytes() for p in files]
    B = max(map(len, data))
    if B == 0:
        raise ValueError("chunks must not be empty")
    records = np.zeros((len(data), B), dtype=np.uint8)
    for i, raw in enumerate(data):
        records[i, :len(raw)] = np.frombuffer(raw, dtype=np.uint8)
    print(f"Loaded {len(data)} chunks; fixed record size {B} bytes", flush=True)
    return records


def handle(conn, scheme, records, xor_server, lwe_server):
    try:
        header, payload = recv_msg(conn)
        op = header.get("op")
        if op == "info":
            send_msg(conn, {"ok": True, "N": int(records.shape[0]), "B": int(records.shape[1]), "scheme": scheme})
        elif scheme == "xor" and op == "xor_answer":
            q = array_from(header, payload, np.uint8)
            if q.ndim != 2 or q.shape[1] != (records.shape[0] + 7) // 8:
                raise ValueError("XOR query has incorrect shape")
            send_msg(conn, {"ok": True}, xor_server.answer(q))
        elif scheme == "lwe" and op == "lwe_hint":
            send_msg(conn, {"ok": True}, lwe_server.hint())
        elif scheme == "lwe" and op == "lwe_answer":
            q = array_from(header, payload, np.uint32)
            if q.ndim != 2 or q.shape[0] != lwe_server.db.shape[1]:
                raise ValueError("LWE query has incorrect shape")
            send_msg(conn, {"ok": True}, lwe_server.answer(q))
        else:
            send_msg(conn, {"ok": False, "error": "unsupported operation for this server"})
    except Exception as exc:
        try:
            send_msg(conn, {"ok": False, "error": str(exc)})
        except Exception:
            pass
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scheme", choices=("xor", "lwe"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--chunks", default="chunks")
    args = ap.parse_args()
    records = load_records(args.chunks)
    xor_server = XorPIRServer(records) if args.scheme == "xor" else None
    lwe_server = LwePIRServer(records, LweParams()) if args.scheme == "lwe" else None
    if lwe_server is not None:
        print("Computing LWE offline hint (one-time setup)...", flush=True)
        lwe_server.hint()
        print(f"LWE hint ready; shape={lwe_server.hint().shape}", flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        server.listen(16)
        print(f"{args.scheme.upper()} PIR server listening on {args.host}:{args.port}", flush=True)
        while True:
            conn, _ = server.accept()
            handle(conn, args.scheme, records, xor_server, lwe_server)


if __name__ == "__main__":
    main()
