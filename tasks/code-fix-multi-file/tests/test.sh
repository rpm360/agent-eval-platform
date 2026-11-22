#!/usr/bin/env bash
set -euo pipefail
pytest -q -o addopts="" -p no:cacheprovider --rootdir=/grader-tests /grader-tests/test_shop.py
