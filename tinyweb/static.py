"""
Tiny Web - pretty simple and powerful web server for tiny platforms like ESP8266 / ESP32
MIT license
(C) Konstantin Belyalov 2017-2018
"""
import os
from .server import HTTPException


def get_file_mime_type(fname):
    mime_types = {'html': 'text/html',
                  'css': 'text/css',
                  'js': 'application/javascript',
                  'png': 'image/png',
                  'jpg': 'image/jpeg',
                  'jpeg': 'image/jpeg',
                  'gif': 'image/gif'}
    idx = fname.rfind('.')
    if idx == -1:
        return 'text/plain'
    ext = fname[idx+1:]
    if ext not in mime_types:
        return 'text/plain'
    else:
        return mime_types[ext]


def send_file(resp, filename, content_type=None):
    """Send file contents"""
    if not content_type:
        content_type = get_file_mime_type(filename)
    resp.add_header('Content-Type', content_type)
    try:
        stat = os.stat(filename)
        resp.add_header('Content-Length', str(stat[6]))
        with open(filename) as f:
            yield from resp._send_response_line()
            yield from resp._send_headers()
            buf = bytearray(128)
            while True:
                size = f.readinto(buf)
                if size == 0:
                    break
                yield from resp.writer.awrite(buf, sz=size)
    except OSError as e:
        raise HTTPException(404)
