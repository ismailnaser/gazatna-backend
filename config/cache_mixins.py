from __future__ import annotations

from rest_framework.response import Response

from config.cache_utils import ANALYTICS_TTL, PUBLIC_TTL, get_or_set, stable_query_key, versioned_key


class CachedAPIViewMixin:
    cache_prefix = "api"
    cache_ttl = PUBLIC_TTL

    def get_cached(self, request, producer):
        key = versioned_key(self.cache_prefix, stable_query_key(request))
        data = get_or_set(key, producer, self.cache_ttl)
        return Response(data)


class CachedReadOnlyViewSetMixin:
    cache_prefix = "api"
    cache_ttl = PUBLIC_TTL

    def list(self, request, *args, **kwargs):
        key = versioned_key(self.cache_prefix, "list", stable_query_key(request))

        def producer():
            response = super(CachedReadOnlyViewSetMixin, self).list(request, *args, **kwargs)
            return response.data

        data = get_or_set(key, producer, self.cache_ttl)
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        pk = kwargs.get("pk", "")
        key = versioned_key(self.cache_prefix, "detail", str(pk))

        def producer():
            response = super(CachedReadOnlyViewSetMixin, self).retrieve(request, *args, **kwargs)
            return response.data

        data = get_or_set(key, producer, self.cache_ttl)
        return Response(data)
