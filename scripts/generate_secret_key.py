#!/usr/bin/env python
"""Generate a new Django SECRET_KEY for production (cPanel env vars)."""

from django.core.management.utils import get_random_secret_key

if __name__ == "__main__":
    print(get_random_secret_key())
