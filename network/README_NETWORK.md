# Network transport for Member A's PIR core

This package wraps the existing `pir_core` split APIs in a small TCP protocol. It does not change either PIR algorithm.

## Requirements

Python 3.10+ and NumPy:

```bash
python -m pip install numpy
```

Run commands from the directory containing `pir_network_server.py`, `pir_network_client.py`, `pir_core/`, and your `chunks/` folder. The server expects sequential files named `chunk_0.bin`, `chunk_1.bin`, etc. Short final chunks are zero-padded to the largest chunk size, consistent with fixed-size PIR records.

## XOR PIR: two server processes

Open two terminals and start one server per terminal:

```bash
python pir_network_server.py xor --port 54100 --chunks chunks
python pir_network_server.py xor --port 54101 --chunks chunks
```

Each server must have the same database, and the two server operators must not collude for the two-server privacy guarantee.

In a third terminal, request global indices 0 and 1:

```bash
python pir_network_client.py xor 0,1 --server0 127.0.0.1:54100 --server1 127.0.0.1:54101
```

## LWE PIR: one server

Start the server:

```bash
python pir_network_server.py lwe --port 54102 --chunks chunks
```

Wait for `LWE hint ready`, then in another terminal:

```bash
python pir_network_client.py lwe 0,1 --server 127.0.0.1:54102
```

The client downloads the offline hint for each invocation in this simple prototype. A later improvement is to cache the hint client-side.

## Important limitations

- This is a local/demo transport, not a production-hardened network protocol. Use only on a trusted lab network; it has no TLS, authentication, or replay protection.
- XOR requests are sent to separate server addresses; do not send both query shares to the same server if claiming two-server privacy.
- LWE server setup computes a potentially expensive offline hint. The core's randomness note says its NumPy PCG64 generator is not a cryptographic RNG, so do not claim production security.
- `chunks/` contains raw byte slices. They are not independently playable video segments; reconstruct the original file by concatenating chunks in index order.
- Retrieved records are padded to fixed record size. Store original byte lengths in a public manifest to trim the final chunk correctly.
- The original C++ server/client remain unchanged and can still be used as a direct-retrieval baseline.
