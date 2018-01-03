"""
Tiny Web - pretty simple and powerful web server for tiny platforms like ESP8266 / ESP32
MIT license
(C) Konstantin Belyalov 2017-2018
"""
import sys
import uasyncio as asyncio
import ujson as json


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

GET = b'GET'
POST = b'POST'
PUT = b'PUT'
HEAD = b'HEAD'
DELETE = b'DELETE'
OPTIONS = b'OPTIONS'


# Supported methods for RESTful API class
restful_methods = {GET: 'get',
                   POST: 'post',
                   PUT: 'put',
                   DELETE: 'delete'}


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

    def add_access_control_headers(self):
        self.add_header('Access-Control-Allow-Origin', self.params['allowed_access_control_origins'])
        self.add_header('Access-Control-Allow-Methods', self.params['allowed_access_control_methods'])
        self.add_header('Access-Control-Allow-Headers', self.params['allowed_access_control_headers'])

    def start_html(self):
        self.add_header('Content-Type', 'text/html')
        yield from self._send_response_line()
        yield from self._send_headers()


def restful_resource_handler(req, resp):
    """Handler for RESTful API endpoins"""
    # Gather data - query string, JSON in request body...
    data = {'a': 1}
    # Call actual handler
    res = req.params['_callmap'][req.method](req.params['_class'], data)

    # Send response
    res_str = json.dumps(res)
    resp.add_header('Content-Type', 'application/json')
    resp.add_header('Content-Length', str(len(res_str)))
    resp.add_access_control_headers()
    yield from resp._send_response_line()
    yield from resp._send_headers()
    yield from resp.send(res_str)


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
            # Read HTTP Request Line
            req = request(reader)
            resp = response(writer)
            yield from req.read_request_line()

            # Find URL handler
            handler, params = self._find_url_handler(req)
            if not handler:
                # No URL handler found - HTTP 404
                yield from resp.error(404)
                return
            req.params = params
            resp.params = params

            # OPTIONS method is handled automatically (if not disabled)
            if params['auto_method_options'] and req.method == OPTIONS:
                resp.add_access_control_headers()
                yield from resp._send_response_line()
                yield from resp._send_headers()
                return

            # Ensure that HTTP method is allowed for this path
            if req.method not in params['methods']:
                yield from resp.error(405)
                return

            # Parse headers, if enabled for this URL
            if params['parse_headers']:
                yield from req.read_headers()

            # Handle URL
            if hasattr(req, '_param'):
                yield from handler(req, resp, req._param)
            else:
                yield from handler(req, resp)
            # Done
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
        # Inital params for route
        params = {'methods': [GET],
                  'parse_headers': True,
                  'max_body_size': 1024,
                  'auto_method_options': True,
                  'allowed_access_control_headers': '*',
                  'allowed_access_control_origins': '*',
                  }
        params.update(kwargs)
        # Pre-create list of methods for OPTIONS
        params['allowed_access_control_methods'] = ' '.join([x.decode() for x in params['methods']])
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
            params['_param_name'] = param
            self.parameterized_url_map[path.encode()] = (f, params)

        if url.encode() in self.explicit_url_map:
            raise ValueError('URL already exists')
        self.explicit_url_map[url.encode()] = (f, params)

    def add_resource(self, cls, url):
        methods = []
        callmap = {}
        # Get all implemented HTTP methods in resource class
        for m, a in restful_methods.items():
            if hasattr(cls, a):
                methods.append(m)
                callmap[m] = getattr(cls, a)
        self.add_route(url, restful_resource_handler, methods=methods, _callmap=callmap, _class=cls)

    def route(self, url, **kwargs):
        def _route(f):
            self.add_route(url, f, **kwargs)
            return f
        return _route

    def run(self, host="127.0.0.1", port=8081, loop_forever=True, backlog=16):
        loop = asyncio.get_event_loop()
        print("* Starting Web Server at {}:{}".format(host, port))
        loop.create_task(asyncio.start_server(self._handler, host, port, backlog=backlog))
        if loop_forever:
            loop.run_forever()
            loop.close()
