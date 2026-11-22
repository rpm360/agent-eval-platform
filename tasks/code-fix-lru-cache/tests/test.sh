#!/usr/bin/env bash
set -euo pipefail
pytest -q -o addopts="" --rootdir=/grader-tests /grader-tests/test_lru.py
