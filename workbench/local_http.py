"""Do not send local model traffic through macOS system proxies."""
import ipaddress
import urllib.parse
import urllib.request


def urlopen(request, timeout=120):
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    host = urllib.parse.urlsplit(url).hostname or ''
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == 'localhost'
    if loopback:
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)
