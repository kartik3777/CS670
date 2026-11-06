#!/usr/bin/env bash
# One command to verify the whole merged project (about 1-2 min). Needs python3, numpy, pandas, matplotlib.
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$PWD"
echo "== [A] pir_core package tests (Member A, shared by network + eval)"
python3 -m unittest discover -s pir_core_extras/tests 2>&1 | tail -3
echo "== [A/B] my PIR core + seekable player tests"
(cd pir && python3 test_pir.py 2>&1 | tail -3 && python3 test_player.py 2>&1 | tail -3)
echo "== [A+B] integration: pir_core backends drive the seekable player"
python3 -m unittest discover -s pir -p "test_pircore*.py" 2>&1 | tail -3
echo "== [D] evaluation & security tests"
(cd security_eval && PYTHONPATH="$PWD:$PYTHONPATH" python3 -m unittest eval.test_eval 2>&1 | tail -3)
echo "== [C] network loopback (XOR x2 servers + LWE) against sample chunks"
python3 network/loopback_check.py
echo "ALL CHECKS PASSED"
