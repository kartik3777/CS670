#!/usr/bin/env python3
"""Client for the XOR/LWE TCP transport wrapper."""
import argparse
import json
import socket
import struct
from pathlib import Path

import numpy as np
from pir_core import XorPIRClient, LwePIRClient, LweParams

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
    if not header.get("ok", False):
        raise RuntimeError(header.get("error", "server request failed"))
    if "shape" in header:
        dtype = np.dtype(header["dtype"])
        shape = tuple(int(x) for x in header["shape"])
        expected = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize
        if expected != len(payload):
            raise ValueError("response shape/payload length mismatch")
        return header, np.frombuffer(payload, dtype=dtype).reshape(shape).copy()
    return header, None


def request(address, header, array=None):
    host, port = address
    payload = b""
    header = dict(header)
    if array is not None:
        array = np.ascontiguousarray(array)
        payload = array.tobytes(order="C")
        header.update(dtype=array.dtype.str, shape=list(array.shape), nbytes=len(payload))
    else:
        header["nbytes"] = 0
    raw_header = json.dumps(header, separators=(",", ":")).encode("utf-8")
    with socket.create_connection((host, port), timeout=120) as sock:
        sock.sendall(struct.pack("!I", len(raw_header)) + raw_header + payload)
        return recv_msg(sock)


def parse_address(value):
    host, port = value.rsplit(":", 1)
    return host, int(port)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scheme", choices=("xor", "lwe"))
    ap.add_argument("indices", help="comma-separated zero-based global chunk indices")
    ap.add_argument("--server", help="server address HOST:PORT (for LWE)")
    ap.add_argument("--server0", help="XOR server 0 address HOST:PORT")
    ap.add_argument("--server1", help="XOR server 1 address HOST:PORT")
    ap.add_argument("--output", default="pir_downloads")
    args = ap.parse_args()
    indices = [int(x.strip()) for x in args.indices.split(",") if x.strip()]
    if not indices or any(i < 0 for i in indices):
        ap.error("indices must be a non-empty list of non-negative integers")
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.scheme == "xor":
        if not args.server0 or not args.server1:
            ap.error("XOR requires --server0 and --server1")
        a0, a1 = parse_address(args.server0), parse_address(args.server1)
        info0, _ = request(a0, {"op": "info"})
        info1, _ = request(a1, {"op": "info"})
        if (info0["N"], info0["B"]) != (info1["N"], info1["B"]):
            raise RuntimeError("XOR servers have different database dimensions")
        N, B = int(info0["N"]), int(info0["B"])
        if any(i >= N for i in indices):
            ap.error(f"index must be less than N={N}")
        cli = XorPIRClient(N, B)
        state, (q0, q1) = cli.query(indices)
        _, ans0 = request(a0, {"op": "xor_answer"}, q0)
        _, ans1 = request(a1, {"op": "xor_answer"}, q1)
        chunks = cli.decode(state, [ans0, ans1])
    else:
        if not args.server:
            ap.error("LWE requires --server")
        addr = parse_address(args.server)
        info, _ = request(addr, {"op": "info"})
        N, B = int(info["N"]), int(info["B"])
        if any(i >= N for i in indices):
            ap.error(f"index must be less than N={N}")
        _, hint = request(addr, {"op": "lwe_hint"})
        cli = LwePIRClient(N, B, hint, LweParams())
        state, Q = cli.query(indices)
        _, ans = request(addr, {"op": "lwe_answer"}, Q)
        chunks = cli.decode(state, ans)

    for index, chunk in zip(indices, chunks):
        path = out_dir / f"chunk_{index}.bin"
        path.write_bytes(chunk.tobytes())
        print(f"Retrieved global index {index}: {len(chunk)} bytes -> {path}")
    print(f"SUCCESS: {len(indices)} chunk(s) retrieved using {args.scheme.upper()} PIR")
    print("Note: output records are fixed-size padded records; consult your manifest for original lengths.")


if __name__ == "__main__":
    main()
