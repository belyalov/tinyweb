"""
Tiny Web - pretty simple and powerful web server / client for tiny platforms like ESP8266 / ESP32
MIT license
"""
import sys
import uasyncio as asyncio


mime_types = {'.html': 'text/html',
              '.css': 'text/css',
              '.js': 'application/javascript',
              '.png': 'image/png',
              '.jpg': 'image/jpeg',
              '.jpeg': 'image/jpeg',
              '.gif': 'image/gif'}

http_status_codes = {200: 'OK',
                     201: 'Created',
                     202: 'Accepted',
                     204: 'No Content',
                     206: 'Partial Content',
                     301: 'Moved Permanently',
                     302: 'Found',
                     303: 'See Other',
                     304: 'Not Modified',
                     400: 'Bad Request',
                     401: 'Unauthorized',
                     403: 'Forbidden',
                     404: 'Not Found',
                     405: 'Method Not Allowed',
                     406: 'Not Acceptable',
                     409: 'Conflict',
                     413: 'Payload Too Large',
                     500: 'Internal Server Error'}


def get_file_mime_type(fname):
    idx = fname.rfind('.')
    if idx == -1:
        return 'text/plain'
    ext = fname[idx:]
    if ext not in mime_types:
        return 'text/plain'
    else:
        return mime_types[ext]


class MalformedHTTP(Exception):
    """Exception for malformed HTTP Request (HTTP 400)"""
    pass


class request:
    """HTTP Request class"""

    def __init__(self, _reader):
        self.reader = _reader
        self.headers = {}
        self.method = b''
        self.path = b''
        self.query_string = b''

    def __repr__(self):
        return '{} {:s} {:s} {:s}\n{}'.format(self.__class__, self.method, self.path,
                                              self.query_string, str(self.headers))

    def read_request_line(self):
        """Read and parser HTTP RequestLine, e.g.:
            GET /something/script?param1=val1 HTTP/1.1
        """
        while True:
            rl = yield from self.reader.readline()
            # skip empty lines
            if rl == b'\r\n' or rl == b'\n':
                continue
            break
        rl_frags = rl.split()
        if len(rl_frags) != 3:
            raise MalformedHTTP('Malformed Request Line')
        self.method = rl_frags[0]
        url_frags = rl_frags[1].split(b'?', 1)
        self.path = url_frags[0]
        if len(url_frags) > 1:
            self.query_string = url_frags[1]

    def read_headers(self):
        """Reads and parses HTTP headers, e.g.:
            Host: google.com
        """
        while True:
            line = yield from self.reader.readline()
            if line == b'\r\n':
                break
            frags = line.split(b':', 1)
            if len(frags) != 2:
                raise MalformedHTTP('Malformed HTTP header')
            self.headers[frags[0]] = frags[1].strip()


class response:
    """HTTP Response class"""

    def __init__(self, _writer):
        self.writer = _writer
        self.send = _writer.awrite
        self.code = 200
        self.headers = {}

    def _send_response_line(self):
        yield from self.send('HTTP/1.0 {} {}\r\n'.
                             format(self.code, http_status_codes[self.code]))

    def _send_headers(self):
        # Because of usually we have only a few HTTP headers (2-5) it doesn't make sense
        # to send them separately - sometimes it could increase latency.
        # So combining headers together and send them as single "packet".
        hdrs = []
        for k, v in self.headers.items():
            hdrs.append('{}: {}'.format(k, v))
        # Empty line after headers
        hdrs.append('\r\n')
        yield from self.send('\r\n'.join(hdrs))

    def error(self, code, message=None):
        self.code = code
        if not message:
            message = 'HTTP {} {}\r\n'.format(self.code, http_status_codes[self.code])
        self.add_header('Content-Type', 'text/plain')
        yield from self._send_response_line()
        yield from self._send_headers()
        yield from self.send(message)

    def add_header(self, key, value):
        self.headers[key] = value

    def add_access_control_headers(self, origins='*', methods='*', headers='*'):
        self.add_header('Access-Control-Allow-Origin', origins)
        self.add_header('Access-Control-Allow-Methods', methods)
        self.add_header('Access-Control-Allow-Headers', headers)

    def start_html(self):
        self.add_header('Content-Type', 'text/html')
        yield from self._send_response_line()
        yield from self._send_headers()


class webserver:
    """Simple web server class"""

    def __init__(self):
        self.explicit_url_map = {}
        self.parameterized_url_map = {}

    def _find_url_handler(self, req):
        """Helper to find URL handler.
           Returns tuple of (function, opts, param) or (None, None) if not found."""
        # First try - lookup in explicit (non parameterized URLs)
        if req.path in self.explicit_url_map:
            return self.explicit_url_map[req.path]
        # Second try - strip last path segment and lookup in another map
        idx = req.path.rfind(b'/') + 1
        path2 = req.path[:idx]
        if len(path2) > 0 and path2 in self.parameterized_url_map:
            # Save parameter into request
            req._param = req.path[idx:].decode()
            return self.parameterized_url_map[path2]
        # No handler found
        return (None, None)

    def _handler(self, reader, writer):
        """Handler for HTTP connection"""
        try:
            req = request(reader)
            resp = response(writer)
            yield from req.read_request_line()
            handler, extra = self._find_url_handler(req)
            if not handler:
                # No URL handler found - HTTP 404
                yield from resp.error(404)
                return
            # Handler found, read / parser HTTP headers
            yield from req.read_headers()
        except MalformedHTTP as e:
            yield from resp.error(400)
        except Exception as e:
            yield from resp.error(500)
            sys.print_exception(e)
        finally:
            yield from writer.aclose()

    def add_route(self, url, f, **kwargs):
        if url == '':
            raise ValueError('Empty URL is not allowed')
        if '?' in url:
            raise ValueError('URL must be simple, without query string')
        # If URL has a parameter
        if url.endswith('>'):
            idx = url.rfind('<')
            if idx == -1:
                raise ValueError('"<" not found in URL')
            path = url[:idx]
            idx += 1
            param = url[idx:-1]
            if path.encode() in self.parameterized_url_map:
                raise ValueError('URL already exists')
            kwargs['param_name'] = param
            self.parameterized_url_map[path.encode()] = (f, kwargs)

        if url.encode() in self.explicit_url_map:
            raise ValueError('URL already exists')
        self.explicit_url_map[url.encode()] = (f, kwargs)

    def route(self, url, **kwargs):
        def _route(f):
            self.add_route(url, f, kwargs)
            return f
        return _route

    def run(self, host="127.0.0.1", port=8081, loop_forever=True, backlog=16):
        loop = asyncio.get_event_loop()
        print("* Starting Web Server at {}:{}".format(host, port))
        loop.create_task(asyncio.start_server(self._handler, host, port, backlog=backlog))
        if loop_forever:
            loop.run_forever()
            loop.close()
