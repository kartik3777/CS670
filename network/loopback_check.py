"""Starts the two XOR servers + the LWE server on localhost, retrieves chunks 0 and last through
pir_network_client.py and compares with the originals (byte-exact, padding all zero)."""
import os, subprocess, sys, tempfile, time, socket
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
env = dict(os.environ, PYTHONPATH=ROOT)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

with tempfile.TemporaryDirectory() as tmp:
    os.makedirs(os.path.join(tmp, "chunks"))
    sizes = [20000] * 5 + [9000]
    orig = []
    for i, n in enumerate(sizes):
        d = os.urandom(n); orig.append(d)
        open(os.path.join(tmp, "chunks", f"chunk_{i}.bin"), "wb").write(d)
    p0, p1, p2 = free_port(), free_port(), free_port()
    srv = lambda mode, port: subprocess.Popen([sys.executable, os.path.join(HERE, "pir_network_server.py"), mode,
                         "--port", str(port), "--chunks", "chunks"], cwd=tmp, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs = [srv("xor", p0), srv("xor", p1), srv("lwe", p2)]
    try:
        for p in (p0, p1, p2):
            for _ in range(120):
                try: socket.create_connection(("127.0.0.1", p), 0.5).close(); break
                except OSError: time.sleep(0.5)
            else: raise SystemExit(f"server on {p} did not start")
        cli = os.path.join(HERE, "pir_network_client.py")
        for args in (["xor", "0,5", "--server0", f"127.0.0.1:{p0}", "--server1", f"127.0.0.1:{p1}"],
                     ["lwe", "0,5", "--server", f"127.0.0.1:{p2}"]):
            subprocess.run([sys.executable, cli] + args, cwd=tmp, env=env, check=True, capture_output=True)
            ddir = os.path.join(tmp, "pir_downloads")
            for i in (0, 5):
                got = open(os.path.join(ddir, f"chunk_{i}.bin"), "rb").read()
                assert got[:len(orig[i])] == orig[i] and not any(got[len(orig[i]):]), (args[0], i)
            print(f"  {args[0]}: chunks 0 and 5 byte-exact")
    finally:
        for pr in procs: pr.kill()
