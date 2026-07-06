# core/cache.py
import time
import threading

class SimpleTTLCache:
    def __init__(self, default_ttl=30):
        self.default_ttl = default_ttl
        self.cache = {}
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.cache:
                value, expiry = self.cache[key]
                if time.time() < expiry:
                    return value
                else:
                    del self.cache[key]
            return None

    def set(self, key, value, ttl=None):
        ttl = ttl if ttl is not None else self.default_ttl
        expiry = time.time() + ttl
        with self.lock:
            self.cache[key] = (value, expiry)

    def invalidate(self, key):
        with self.lock:
            # Delete both the exact key and any workspace-suffixed keys (e.g. key_1)
            keys_to_delete = [k for k in self.cache.keys() if k == key or k.startswith(f"{key}_")]
            for k in keys_to_delete:
                del self.cache[k]

    def clear(self):
        with self.lock:
            self.cache.clear()

# Global instance for dashboard caching
dashboard_cache = SimpleTTLCache(default_ttl=30)
