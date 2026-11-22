import sys
sys.path.insert(0, "/workspace")

from search import binary_search


def test_finds_every_element():
    arr = [1, 3, 5, 7, 9, 11]
    for i, v in enumerate(arr):
        assert binary_search(arr, v) == i


def test_single_element():
    assert binary_search([4], 4) == 0
    assert binary_search([4], 5) == -1


def test_missing_and_empty():
    assert binary_search([1, 3, 5], 4) == -1
    assert binary_search([], 1) == -1
