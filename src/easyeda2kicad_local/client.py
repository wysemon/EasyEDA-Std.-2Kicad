"""Sequential, paced public-component access with no third-party destinations."""

import logging
import math
import random
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from .files import MAX_INPUT_BYTES

log = logging.getLogger(__name__)
EDITOR_VERSION = '6.5.60'
UUID = re.compile(r'^[a-fA-F0-9]{32}$')
HEADERS = {
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://easyeda.com/editor',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
}


class FetchError(Exception):
    """One component could not be fetched; independent items may continue."""


class StopRun(FetchError):
    """Access restrictions require stopping the whole batch, including retries."""


def parse_uuid(value):
    """Normalize a UUID or approved component URL without fetching anything."""
    value = value.strip()
    if UUID.fullmatch(value):
        return value.lower()
    url = urlsplit(value)
    parts = url.path.rstrip('/').split('/')
    if (
        url.scheme != 'https'
        or url.netloc.lower() not in ('easyeda.com', 'www.easyeda.com')
        or len(parts) != 3
        or parts[1] != 'component'
        or not UUID.fullmatch(parts[-1])
    ):
        raise ValueError(f'Expected a 32-hex UUID or https://easyeda.com/component/<uuid>: {value}')
    return parts[-1].lower()


class EasyEDAClient:
    """Own one sequential connection pool and pacing state for an entire batch.

    Injectable timing and transport keep retry tests offline and instantaneous.
    The denial counter intentionally survives calls to ``component()``.
    """

    def __init__(
        self,
        delay=4.0,
        *,
        client=None,
        sleep=time.sleep,
        clock=time.monotonic,
        jitter=lambda: random.uniform(0, 2),
    ):
        if not math.isfinite(delay) or delay < 1:
            raise ValueError('--delay must be at least 1 second and finite')
        self.http = client or httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=False)
        self.delay, self.sleep, self.clock, self.jitter = delay, sleep, clock, jitter
        self.next_request = 0.0
        self.denied = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.http.close()

    def request(self, url, *, params=None):
        """Fetch approved HTTPS bytes with bounded retries and a shared cooldown."""
        target = urlsplit(url)
        if target.scheme != 'https' or target.netloc != 'easyeda.com':
            raise FetchError('Refusing destination outside EasyEDA')
        for attempt in range(3):
            self.sleep(max(0.0, self.next_request - self.clock()))
            try:
                with self.http.stream(
                    'GET', url, params=params, headers=HEADERS, follow_redirects=False
                ) as response:
                    # Count denials before reading a body, including across items.
                    if response.status_code in (403, 429):
                        self.denied += 1
                        if self.denied >= 2:
                            raise StopRun(
                                'Two consecutive 429/403 responses; stopping the whole run. Wait before retrying and check that the component is public; do not bypass access restrictions.'
                            )
                    else:
                        self.denied = 0
                    content = bytearray()
                    if response.is_success:
                        for chunk in response.iter_bytes(chunk_size=65_536):
                            if len(content) + len(chunk) > MAX_INPUT_BYTES:
                                raise FetchError(
                                    'Component response exceeds 16 MiB; no conversion attempted'
                                )
                            content.extend(chunk)
            except httpx.RequestError as e:
                raise FetchError(
                    f'Network request failed ({type(e).__name__}); check your internet connection/proxy and retry.'
                ) from e
            finally:
                self.next_request = self.clock() + self.delay + self.jitter()
            if response.status_code in (403, 429) or 500 <= response.status_code <= 599:
                if attempt == 2:
                    raise FetchError(
                        f'HTTP {response.status_code} after 3 tries; wait and retry later, and check that the component is public.'
                    )
                wait = 30 * 2**attempt
                retry = response.headers.get('Retry-After')
                if retry:
                    try:
                        seconds = float(retry)
                        if math.isnan(seconds):
                            raise ValueError('invalid Retry-After')
                        wait = max(0.0, seconds)
                    except ValueError:
                        try:
                            date = parsedate_to_datetime(retry)
                            wait = max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            pass
                if wait > 300:
                    log.warning('Retry-After exceeds 300 seconds; capped at 300 seconds.')
                    wait = 300.0
                log.warning(
                    'HTTP %s; retrying in at least %.1f seconds', response.status_code, wait
                )
                self.next_request = max(self.next_request, self.clock() + wait)
                continue
            if not response.is_success:
                raise FetchError(
                    f'HTTP {response.status_code}; redirects and authentication are not followed; check that the link is a public Standard component.'
                )
            return bytes(content)
        raise AssertionError('unreachable')

    def component(self, uuid):
        """Use the same public endpoint for symbols and footprint fallbacks."""
        if not UUID.fullmatch(uuid):
            raise FetchError('invalid component UUID')
        return self.request(
            f'https://easyeda.com/api/components/{uuid}',
            params={'version': EDITOR_VERSION, 'uuid': uuid},
        )
