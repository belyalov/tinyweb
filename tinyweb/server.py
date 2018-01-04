"""
Tiny Web - pretty simple and powerful web server for tiny platforms like ESP8266 / ESP32
MIT license
(C) Konstantin Belyalov 2017-2018
"""
import uasyncio as asyncio
import ujson as json
import gc


def urldecode_plus(s):
    """Decode urlencoded string and decode '+' char (convert to space)"""
    s = s.replace('+', ' ')
    arr1 = s.split('%')
    arr2 = [arr1[0]]
    for it in arr1[1:]:
        if len(it) >= 2:
            arr2.append(chr(int(it[:2], 16)) + it[2:])
        elif len(it) == 0:
            arr2.append('%')
        else:
            arr2.append(it)
    return ''.join(arr2)


def parse_query_string(s):
    """Parse urlencoded string into dict"""
    res = {}
    pairs = s.split('&')
    for p in pairs:
        vals = [urldecode_plus(x) for x in p.split('=', 1)]
        if len(vals) == 1:
            res[vals[0]] = ''
        else:
            res[vals[0]] = vals[1]
    return res


class HTTPException(Exception):
    """HTTP based expections"""

    def __init__(self, code=400):
        self.code = code


class request:
    """HTTP Request class"""

    def __init__(self, _reader):
        self.reader = _reader
        self.headers = {}
        self.method = b''
        self.path = b''
        self.query_string = b''

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
            raise HTTPException(400)
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
                raise HTTPException(400)
            self.headers[frags[0]] = frags[1].strip()

    def read_parse_form_data(self):
        # TODO: Probably there is better solution how to handle
        # request body, at least for simple urlencoded forms - by processing
        # chunks instead of accumulating payload.
        gc.collect()
        if b'Content-Length' not in self.headers:
            raise HTTPException(400)
        size = int(self.headers[b'Content-Length'])
        if size > self.params['max_body_size'] or size < 0:
            raise HTTPException(413)
        data = yield from self.reader.readexactly(size)
        # Parse payload depending on content type
        if b'Content-Type' not in self.headers:
            # Unknown content type
            return data
        ct = self.headers[b'Content-Type']
        try:
            if ct == b'application/json':
                return json.loads(data)
            elif ct == b'application/x-www-form-urlencoded':
                return parse_query_string(data)
        except ValueError:
            # Re-generate exception for malformed form data
            raise HTTPException(400)


class response:
    """HTTP Response class"""

    def __init__(self, _writer):
        self.writer = _writer
        self.send = _writer.awrite
        self.code = 200
        self.headers = {}
        self.http_status_codes = {200: 'OK',
                                  201: 'Created',
                                  302: 'Found',
                                  304: 'Not Modified',
                                  400: 'Bad Request',
                                  403: 'Forbidden',
                                  404: 'Not Found',
                                  405: 'Method Not Allowed',
                                  413: 'Payload Too Large',
                                  500: 'Internal Server Error'}

    def _send_response_line(self):
        if self.code in self.http_status_codes:
            msg = self.http_status_codes[self.code]
        else:
            msg = 'NA'
        yield from self.send('HTTP/1.0 {} {}\r\n'.format(self.code, msg))

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

    def error(self, code):
        self.code = code
        yield from self._send_response_line()
        yield from self.send('\r\n')

    def add_header(self, key, value):
        self.headers[key] = value

    def add_access_control_headers(self):
        self.add_header('Access-Control-Allow-Origin', self.params['allowed_access_control_origins'])
        self.add_header('Access-Control-Allow-Methods', b' '.join(self.params['methods']))
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
        gc.collect()

        try:
            # Read HTTP Request Line
            req = request(reader)
            resp = response(writer)
            yield from req.read_request_line()

            # Find URL handler
            handler, params = self._find_url_handler(req)
            if not handler:
                # No URL handler found - HTTP 404
                raise HTTPException(404)
            req.params = params
            resp.params = params

            # OPTIONS method is handled automatically (if not disabled)
            if req.method == b'OPTIONS':
                resp.add_access_control_headers()
                yield from resp._send_response_line()
                yield from resp._send_headers()
                return

            # Ensure that HTTP method is allowed for this path
            if req.method not in params['methods']:
                raise HTTPException(405)

            # Parse headers, if enabled for this URL
            if params['parse_headers']:
                yield from req.read_headers()

            # Handle URL
            gc.collect()
            if hasattr(req, '_param'):
                yield from handler(req, resp, req._param)
            else:
                yield from handler(req, resp)
            # Done
        except HTTPException as e:
            yield from resp.error(e.code)
        except Exception as e:
            yield from resp.error(500)
            raise
        finally:
            yield from writer.aclose()

    def add_route(self, url, f, **kwargs):
        if url == '' or '?' in url:
            raise ValueError('Invalid URL')
        # Inital params for route
        params = {'methods': ['GET'],
                  'parse_headers': True,
                  'max_body_size': 1024,
                  'allowed_access_control_headers': '*',
                  'allowed_access_control_origins': '*',
                  }
        params.update(kwargs)
        # Convert methods to bytestring
        params['methods'] = [x.encode() for x in params['methods']]
        # If URL has a parameter
        if url.endswith('>'):
            idx = url.rfind('<')
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
        for m in ['GET', 'POST', 'PUT', 'DELETE']:
            fn = m.lower()
            if hasattr(cls, fn):
                methods.append(m)
                callmap[m.encode()] = getattr(cls, fn)
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
