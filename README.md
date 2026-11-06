# Private video streaming with PIR

A video player whose server cannot tell which video, or which part of a video, you are watching.

The catalog is cut into equal-size chunks. The player fetches every chunk with Private Information Retrieval (PIR), so the query the server receives looks the same whichever chunk was wanted. The project implements two PIR schemes, a seekable player on top of them, TCP servers, and an evaluation of two questions that decide whether this is practical:

1. **Does it keep up with playback?** (cost in data, compute and start-up time)
2. **Is it actually private?** (PIR hides *what* you ask for, but not *how much* you ask for)

CS670, IIT Kanpur, Group 9, instructor Prof. Adithya Vadapalli.
Team: Kartik (PIR core), Sabhyasachi (player), Lokesh Kumar Moond (network and servers), Krishna Chandu Pujari (evaluation and security).

A full write-up with method, tables and caveats is in [`docs/PROJECT_REPORT.pdf`](docs/PROJECT_REPORT.pdf).

---

## What we found

Measured on a real video cut into 97 chunks of 367 KB (35 MB, 2 seconds of video per chunk):

| | Two-server XOR | Single-server LWE |
|---|---|---|
| Servers needed | 2, must not collude | 1 |
| Data for one 367 KB chunk | 734 KB down, almost nothing up (about 2x) | 1,504 KB up and 1,468 KB down (about 8x) |
| Server compute, batch of 1 to 16 chunks | 10 to 134 ms | 158 to 2,707 ms |
| Time to fetch one chunk at 10 Mbit/s | 0.61 s (limit is 2 s) | 2.56 s, too slow |
| Link speed needed to keep up | about 3 Mbit/s | about 13 Mbit/s |

And on the privacy side, from simulated sessions with a 200-video catalog:

- One XOR server guessing the wanted chunk is right 1.06% of the time; pure chance is 1.03%. If both servers pool their queries it is 100%.
- The **traffic pattern still leaks**. An attacker who sees only request counts and batch sizes names the video 30% of the time (a popularity-only guess gets 10%), and detects seeks in 98.7% of sessions.
- Padding the last batch with dummy chunks cuts the attack to 6.9% for 2% more bandwidth. Constant-rate traffic cuts it to 0.7% and hides seeks, for 8.75x the bandwidth.

Read the [limits](#limits-read-before-quoting-numbers) before using any number.

---

## Try it

You need Python 3 with `numpy`, `pandas` and `matplotlib`. A C compiler is optional (the C kernels fall back to numpy).

```bash
./run_all_checks.sh
```

This runs every test suite and a network loopback check (one to two minutes). It should end with `ALL CHECKS PASSED`.

### Use the PIR package directly

```python
import numpy as np
from pir_core import XorPIR, LwePIR

records = np.random.default_rng(0).integers(0, 256, (97, 1024), dtype=np.uint8)  # 97 chunks of 1 KB

pir = XorPIR()              # or LwePIR()
pir.setup(records)
chunks = pir.retrieve([3, 50, 96])        # a batch of three chunks, fetched privately
assert (chunks[0] == records[3]).all()
print(pir.last_stats)                      # bytes up/down, query, server and decode time
```

`XorPIR` and `LwePIR` have the same interface. For a real client/server split (so a socket can sit between them) use `XorPIRClient`/`XorPIRServer` and `LwePIRClient`/`LwePIRServer`.

### Reproduce the experiments

```bash
export PYTHONPATH=$PWD

# non-private baseline: HTTP chunk server + playback client
(cd baseline && python3 run_demo.py)

# playback grid (links x batch sizes x seeks) -> pir/results/
(cd pir && python3 eval_playback.py)

# attackers and countermeasures, about 5 minutes -> security_eval/results/
(cd security_eval && python3 -m eval.run_all)

# your own video: cut it into 2 s segments, then run PIR over the real chunks
ffmpeg -i my.mp4 -c copy -f segment -segment_time 2 seg/video1/%03d.ts
BW_MBPS=10 python3 pir_core_extras/run_catalog.py xor seg/video1
BW_MBPS=10 python3 pir_core_extras/run_catalog.py lwe seg/video1
```

`run_catalog.py` measures compute, calculates transfer time from the byte counts and the link speed you give it, and says whether each batch size is fast enough to keep up with playback.

### Run the TCP servers

XOR needs two server processes on two ports, each holding the same chunks. LWE needs one.

```bash
cd network
python3 split_video.py                                   # writes chunks/chunk_N.bin
python3 pir_network_server.py xor --port 54100 --chunks chunks &
python3 pir_network_server.py xor --port 54101 --chunks chunks &
python3 pir_network_server.py lwe --port 54102 --chunks chunks &    # wait for "LWE hint ready"

python3 pir_network_client.py xor 0,1 --server0 127.0.0.1:54100 --server1 127.0.0.1:54101
python3 pir_network_client.py lwe 0,1 --server 127.0.0.1:54102
```

Details and the C++ baseline server are in `network/README_NETWORK.md`.

---

## How it works

```
 manifest (public: offsets, true lengths, SHA-256 per chunk)
        |
     Player ----- chunk indices ----> PIR client ---- q0 ----> XOR server 0
 buffer, batching,                    builds queries  - q1 ---> XOR server 1     (XOR: two servers)
 seeks, hash check                    decodes answers - query -> LWE server      (LWE: one server)
```

**Chunks and the manifest.** Every chunk is zero-padded to one catalog-wide size, because a different record size would reveal which record was returned. The manifest is public and holds each chunk's true length and SHA-256, so the player can trim padding and verify what PIR returned.

**XOR scheme.** The client picks a random bit-vector q0 with one bit per chunk and makes q1 by flipping the bit of the wanted chunk. Each server XORs the chunks selected by its vector. XORing the two answers leaves only the wanted chunk. One vector alone is uniformly random, so one server learns nothing even with unlimited computing power. Both vectors together give away the answer (q0 XOR q1 has a single 1), so the servers must be run by independent parties.

**LWE scheme (SimplePIR style).** One server holds the database as a byte matrix. The client downloads a one-time hint H = DB·A. A query is A·s + e + Δ·u for a fresh secret s, small noise e and a marker u for the wanted column. The server multiplies its database by the query, and the client subtracts H·s and rounds to get the bytes. Parameters: q = 2^32, plaintext modulus 2^8, n = 1024, noise standard deviation 6.4. Reusing a secret would leak (there is a test for that), so every query gets a new one.

**Player.** It keeps a buffer, fetches *k* chunks per batch so the server can share work, jumps on a seek and throws away any in-flight request for the old position, and plays a chunk only after its SHA-256 matches the manifest.

**What PIR does not hide.** The server still sees when requests arrive and how many chunks each asks for. That is enough to guess the video from its length and to spot a seek. The `security_eval/` code measures this and tests three fixes (pad the last batch, round the length up, send at a constant rate).

---

## Repository map

| Folder | What is in it |
|---|---|
| `pir_core/` | The shared PIR package: XOR and LWE with a split client/server API. The network and evaluation code import this. |
| `pir_core_extras/` | 20 tests for `pir_core`, the real-catalog script `run_catalog.py`, and the raw run output in `results/real_catalog_run.txt` |
| `pir/` | A second, independent PIR implementation with C kernels (server time up to 1 GiB catalogs), the seekable player (`player.py`), playback experiments, `pircore_backend.py` to run the player on `pir_core` |
| `baseline/` | Non-private HTTP chunk server and playback client, same metrics as the PIR runs |
| `network/` | C++ chunk server, Python TCP servers and client for XOR (2 processes) and LWE, benchmark and loopback test |
| `security_eval/` | Threat model, session simulator, attackers, countermeasures, result CSVs and figures, the evaluation report |
| `docs/` | Project report (PDF), literature survey, implementation plan, script for slides 18 to 22 |

Tests: 20 (`pir_core`) + 16 (`pir`) + 15 (player) + 1 (adapter) + 6 (evaluation) + the network loopback check.

---

## Limits (read before quoting numbers)

- **Network time is calculated, not measured.** Transfer time comes from byte counts and an assumed link speed. The two XOR servers ran on one machine.
- **Small catalog.** The real run is one 35 MB video. Server time was measured up to 1 GiB (XOR) and 64 MB (LWE) only; larger figures are extrapolated.
- **Noisy timings.** LWE compute differed by up to about 50% between two runs. Use the numbers as orders of magnitude.
- **The experiments use different set-ups** (1 Mbit/s stream with 128 KiB chunks in `pir/`; 2 s chunks of 367 KB in `security_eval/`). Compare trends, not absolute values.
- **The LWE code is not hardened.** It uses NumPy's non-cryptographic random generator and its parameters were never checked with a lattice estimator. The privacy test for it is a sanity check, not a proof.
- **No integrity or transport security.** A malicious server can return wrong answers, and there is no TLS, login or signed manifest.
- **The traffic defences are simulated.** They are not in the real player yet, and the attacker only uses request counts and batch sizes.
- **The network layer is not wired to the player.** The player uses the PIR backends in-process; a TCP-backed chunk source is the next step.

## Next steps

Connect the TCP servers to the player and test on a real network with two independent XOR hosts; run larger catalogs with sharding; replace the random generator and check LWE parameters; add a signed manifest, answer verification and TLS; put last-batch padding into the real player.

## Background reading

Chor, Goldreich, Kushilevitz and Sudan (XOR PIR, 1998); Henzinger et al., SimplePIR (USENIX Security 2023); Gupta et al., Popcorn (NSDI 2016); Ahmad et al., Addra (OSDI 2021). The group's survey is in `docs/`.
