# -*- coding: utf-8 -*-
"""Implements a simple wrapper around urlopen."""
import logging
from functools import lru_cache
import random
import re
import json
from urllib import parse
from urllib.request import Request
from urllib.request import urlopen

from pytube.exceptions import RegexMatchError
from pytube.helpers import regex_search

logger = logging.getLogger(__name__)
default_chunk_size = 4096  # 4kb
default_range_size = 9437184  # 9MB

USER_AGENTS = [
        # Firefox
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:86.0) Gecko/20100101 Firefox/86.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 11.2; rv:86.0) Gecko/20100101 Firefox/86.0",
        "Mozilla/5.0 (X11; Linux i686; rv:86.0) Gecko/20100101 Firefox/86.0",
        "Mozilla/5.0 (Linux x86_64; rv:86.0) Gecko/20100101 Firefox/86.0",
        "Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:86.0) Gecko/20100101 Firefox/86.0",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:86.0) Gecko/20100101 Firefox/86.0",
        "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:86.0) Gecko/20100101 Firefox/86.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 11_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/32.0 Mobile/15E148 Safari/605.1.15",
        "Mozilla/5.0 (iPad; CPU OS 11_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/32.0 Mobile/15E148 Safari/605.1.15",
        "Mozilla/5.0 (iPod touch; CPU iPhone OS 11_2_3 like Mac OS X) AppleWebKit/604.5.6 (KHTML, like Gecko) FxiOS/32.0 Mobile/15E148 Safari/605.1.15",
        "Mozilla/5.0 (Android 11; Mobile; rv:68.0) Gecko/68.0 Firefox/86.0",
        "Mozilla/5.0 (Android 11; Mobile; LG-M255; rv:86.0) Gecko/86.0 Firefox/86.0",
        # Chrome
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.82 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.82 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.82 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_2_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.82 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.82 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/87.0.4280.77 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPad; CPU OS 14_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/87.0.4280.77 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPod; CPU iPhone OS 14_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/87.0.4280.77 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.86 Mobile Safari/537.36",
]


def _execute_request(url, method=None, headers=None, data=None):
    base_headers = {"User-Agent": random.choice(USER_AGENTS), "accept-language": "en-US,en"}
    if headers:
        base_headers.update(headers)
    if data:
        # encode data for request
        if not isinstance(data, bytes):
            data = bytes(json.dumps(data), encoding="utf-8")
    if url.lower().startswith("http"):
        request = Request(url, headers=base_headers, method=method, data=data)
    else:
        raise ValueError("Invalid URL")
    return urlopen(request)  # nosec


def get(url, extra_headers=None):
    """Send an http GET request.

    :param str url:
        The URL to perform the GET request for.
    :param dict extra_headers:
        Extra headers to add to the request
    :rtype: str
    :returns:
        UTF-8 encoded string of response
    """
    if extra_headers is None:
        extra_headers = {}
    return _execute_request(url, headers=extra_headers).read().decode("utf-8")


def post(url, extra_headers=None, data=None):
    """Send an http POST request.

    :param str url:
        The URL to perform the POST request for.
    :param dict extra_headers:
        Extra headers to add to the request
    :param dict data:
        The data to send on the POST request
    :rtype: str
    :returns:
        UTF-8 encoded string of response
    """
    # could technically be implemented in get,
    # but to avoid confusion implemented like this
    if extra_headers is None:
        extra_headers = {}
    if data is None:
        data = {}
    # required because the youtube servers are strict on content type
    # raises HTTPError [400]: Bad Request otherwise
    extra_headers.update({"Content-Type": "application/json"})
    return _execute_request(url, headers=extra_headers, data=data).read().decode("utf-8")


def seq_stream(url, chunk_size=default_chunk_size, range_size=default_range_size):
    """Read the response in sequence.
    :param str url: The URL to perform the GET request for.
    :param int chunk_size: The size in bytes of each chunk. Defaults to 4KB
    :param int range_size: The size in bytes of each range request. Defaults
    to 9MB
    :rtype: Iterable[bytes]
    """
    # YouTube expects a request sequence number as part of the parameters.
    split_url = parse.urlsplit(url)
    base_url = '%s://%s/%s?' % (split_url.scheme, split_url.netloc, split_url.path)

    querys = dict(parse.parse_qsl(split_url.query))

    # The 0th sequential request provides the file headers, which tell us
    #  information about how the file is segmented.
    querys['sq'] = 0
    url = base_url + parse.urlencode(querys)

    segment_data = b''
    for chunk in stream(url):
        yield chunk
        segment_data += chunk

    # We can then parse the header to find the number of segments
    stream_info = segment_data.split(b'\r\n')
    segment_count_pattern = re.compile(b'Segment-Count: (\\d+)')
    for line in stream_info:
        match = segment_count_pattern.search(line)
        if match:
            segment_count = int(match.group(1).decode('utf-8'))

    # We request these segments sequentially to build the file.
    seq_num = 1
    while seq_num <= segment_count:
        # Create sequential request URL
        querys['sq'] = seq_num
        url = base_url + parse.urlencode(querys)

        yield from stream(url)
        seq_num += 1
    return  # pylint: disable=R1711


def stream(url, chunk_size=default_chunk_size, range_size=default_range_size):
    """Read the response in chunks.
    :param str url: The URL to perform the GET request for.
    :param int chunk_size: The size in bytes of each chunk. Defaults to 4KB
    :param int range_size: The size in bytes of each range request. Defaults
    to 9MB
    :rtype: Iterable[bytes]
    """
    file_size: int = range_size  # fake filesize to start
    downloaded = 0
    while downloaded < file_size:
        stop_pos = min(downloaded + range_size, file_size) - 1
        range_header = f"bytes={downloaded}-{stop_pos}"
        response = _execute_request(
            url, method="GET", headers={"Range": range_header}
        )
        if file_size == range_size:
            try:
                content_range = response.info()["Content-Range"]
                file_size = int(content_range.split("/")[1])
            except (KeyError, IndexError, ValueError) as e:
                logger.error(e)
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            downloaded += len(chunk)
            yield chunk
    return  # pylint: disable=R1711


@lru_cache()
def filesize(url):
    """Fetch size in bytes of file at given URL

    :param str url: The URL to get the size of
    :returns: int: size in bytes of remote file
    """
    return int(head(url)["content-length"])


@lru_cache()
def seq_filesize(url):
    """Fetch size in bytes of file at given URL from sequential requests

    :param str url: The URL to get the size of
    :returns: int: size in bytes of remote file
    """
    total_filesize = 0
    # YouTube expects a request sequence number as part of the parameters.
    split_url = parse.urlsplit(url)
    base_url = '%s://%s/%s?' % (split_url.scheme, split_url.netloc, split_url.path)
    querys = dict(parse.parse_qsl(split_url.query))

    # The 0th sequential request provides the file headers, which tell us
    #  information about how the file is segmented.
    querys['sq'] = 0
    url = base_url + parse.urlencode(querys)
    response = _execute_request(
        url, method="GET"
    )

    response_value = response.read()
    # The file header must be added to the total filesize
    total_filesize += len(response_value)

    # We can then parse the header to find the number of segments
    segment_count = 0
    stream_info = response_value.split(b'\r\n')
    segment_regex = b'Segment-Count: (\\d+)'
    for line in stream_info:
        # One of the lines should contain the segment count, but we don't know
        #  which, so we need to iterate through the lines to find it
        try:
            segment_count = int(regex_search(segment_regex, line, 1))
        except RegexMatchError:
            pass

    if segment_count == 0:
        raise RegexMatchError('seq_filesize', segment_regex)

    # We make HEAD requests to the segments sequentially to find the total filesize.
    seq_num = 1
    while seq_num <= segment_count:
        # Create sequential request URL
        querys['sq'] = seq_num
        url = base_url + parse.urlencode(querys)

        total_filesize += int(head(url)['content-length'])
        seq_num += 1
    return total_filesize


def head(url):
    """Fetch headers returned http GET request.

    :param str url:
        The URL to perform the GET request for.
    :rtype: dict
    :returns:
        dictionary of lowercase headers
    """
    response_headers = _execute_request(url, method="HEAD").info()
    return {k.lower(): v for k, v in response_headers.items()}
