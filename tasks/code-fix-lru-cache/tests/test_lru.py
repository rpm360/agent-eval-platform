import sys
sys.path.insert(0, "/workspace")

from lru import LRUCache


def test_lru_evicts_least_recently_used():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # 'a' is now MRU, 'b' is LRU
    cache.put("c", 3)           # should evict 'b'
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_lru_update_existing_key():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    cache.put("c", 3)           # should evict 'b'
    assert cache.get("a") == 10
    assert cache.get("b") is None
    assert cache.get("c") == 3
