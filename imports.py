"""Optional imports isolated from the always-available local upload path."""
import ipaddress
import os
from pathlib import Path
import socket
from urllib.parse import urlsplit
import urllib.request


def validate_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a public HTTP(S) media URL without embedded credentials.')
    if parsed.port not in (None, 80, 443):
        raise ValueError('Only standard HTTP(S) ports are supported')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private, loopback, reserved and local network URLs are not supported')
    return parsed


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_media(url, destination, ensure_space):
    validate_url(url)
    # Keep inherited proxies and TLS verification. Validate every redirect target.
    opener = urllib.request.build_opener(PublicRedirect())
    request = urllib.request.Request(url, headers={'User-Agent': 'ClipForge/1.0'})
    with opener.open(request, timeout=30) as response:
        content_type = response.headers.get_content_type()
        if content_type.startswith('text/'):
            raise ValueError(f'URL returned {content_type}, not a media file. Download an authorized video and upload it locally.')
        with Path(destination).open('xb') as output:
            while block := response.read(1024 * 1024):
                ensure_space(len(block)); output.write(block)
