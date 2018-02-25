"""
Tiny Web - pretty simple and powerful web server for tiny platforms like ESP8266 / ESP32
MIT license
(C) Konstantin Belyalov 2017-2018
"""
import uasyncio as asyncio
import ujson as json
import gc
import os


def urldecode_plus(s):
    """Decode urlencoded string (including '+' char).

    Returns decoded string
    """
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
    """Parse urlencoded string andinto dict.

    Returns dict
    """
    res = {}
    pairs = s.split('&')
    for p in pairs:
        vals = [urldecode_plus(x) for x in p.split('=', 1)]
        if len(vals) == 1:
            res[vals[0]] = ''
        else:
            res[vals[0]] = vals[1]
    return res


def get_file_mime_type(fname):
    """Get MIME type by filename extension.

    Returns string
    """
    mime_types = {'.html': 'text/html',
                  '.css': 'text/css',
                  '.js': 'application/javascript',
                  '.png': 'image/png',
                  '.jpg': 'image/jpeg',
                  '.jpeg': 'image/jpeg',
                  '.gif': 'image/gif'}
    idx = fname.rfind('.')
    if idx == -1:
        return 'text/plain'
    ext = fname[idx:]
    if ext not in mime_types:
        return 'text/plain'
    else:
        return mime_types[ext]


class HTTPException(Exception):
    """HTTP protocol expections"""

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
        """Read and parse first line (AKA HTTP Request Line).
        Function is generator.

        Request line is something like:
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
        """Read and parse HTTP headers until \r\n\r\n:
        Function is generator.

        HTTP headers are:
        Host: google.com
        Content-Type: blah
        \r\n
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
        """Read HTTP form data (payload), if any.
        Function is generator.

        Returns:
            - dict of key / value pairs
            - None in case of no form data present
        """
        # TODO: Probably there is better solution how to handle
        # request body, at least for simple urlencoded forms - by processing
        # chunks instead of accumulating payload.
        gc.collect()
        if b'Content-Length' not in self.headers:
            return {}
        # Parse payload depending on content type
        if b'Content-Type' not in self.headers:
            # Unknown content type, return unparsed, raw data
            return {}
        size = int(self.headers[b'Content-Length'])
        if size > self.params['max_body_size'] or size < 0:
            raise HTTPException(413)
        data = yield from self.reader.readexactly(size)
        # Use only string before ';', e.g:
        # application/x-www-form-urlencoded; charset=UTF-8
        ct = self.headers[b'Content-Type'].split(b';', 1)[0]
        try:
            if ct == b'application/json':
                return json.loads(data)
            elif ct == b'application/x-www-form-urlencoded':
                return parse_query_string(data.decode())
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
        """Compose and send HTTP response line.
        Function is generator.
        """
        if self.code in self.http_status_codes:
            msg = self.http_status_codes[self.code]
        else:
            msg = 'NA'
        yield from self.send('HTTP/1.0 {} {}\r\n'.format(self.code, msg))

    def _send_headers(self):
        """Compose and send HTTP headers following by \r\n.
        This function is generator.
        """
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
        """Generate HTTP error response
        This function is generator.

        Arguments:
            code - HTTP response code

        Example:
            # Not enough permissions. Send HTTP 403 - Forbidden
            yield from resp.error(403)
        """
        self.code = code
        yield from self._send_response_line()
        yield from self.send('\r\n')

    def redirect(self, location):
        """Generate HTTP redirect response to 'location'.
        Basically it will generate HTTP 302 with 'Location' header

        Arguments:
            location - URL to redirect to

        Example:
            # Redirect to /something
            yield from resp.redirect('/something')
        """
        self.code = 302
        self.add_header('Location', location)
        yield from self._send_response_line()
        yield from self._send_headers()

    def add_header(self, key, value):
        """Add HTTP response header

        Arguments:
            key - header name
            value - header value

        Example:
            resp.add_header('Content-Encoding', 'gzip')
        """
        self.headers[key] = value

    def add_access_control_headers(self):
        """Add Access Control related HTTP response headers.
        This is required when working with RestApi (JSON requests)
        """
        self.add_header('Access-Control-Allow-Origin', self.params['allowed_access_control_origins'])
        self.add_header('Access-Control-Allow-Methods', self.params['allowed_access_control_methods'])
        self.add_header('Access-Control-Allow-Headers', self.params['allowed_access_control_headers'])

    def start_html(self):
        """Start response with HTML content type.
        This function is generator.

        Example:
            yield from resp.start_html()
            yield from resp.send('<html><h1>Hello, world!</h1></html>')
        """
        self.add_header('Content-Type', 'text/html')
        yield from self._send_response_line()
        yield from self._send_headers()

    def send_file(self, filename, content_type=None, max_age=2592000):
        """Send local file as HTTP response.
        This function is generator.

        Arguments:
            filename - Name of file which exists in local filesystem
        Keyword arguments:
            content_type - Filetype. By default - None means auto-detect.
            max_age - Cache control. How long browser can keep this file on disk.
                      By default - 30 days
                      Set to 0 - to disable caching.

        Example 1: Default use case:
            yield from resp.send_file('images/cat.jpg')

        Example 2: Disable caching:
            yield from resp.send_file('static/index.html', max_age=0)

        Example 3: Override content type:
            yield from resp.send_file('static/file.bin', content_type='application/octet-stream')
        """
        try:
            # Get file size
            stat = os.stat(filename)
            slen = str(stat[6])
            self.add_header('Content-Length', slen)
            # Find content type
            if not content_type:
                content_type = get_file_mime_type(filename)
            self.add_header('Content-Type', content_type)
            # Since this is static content is totally make sense
            # to tell browser to cache it, however, you can always
            # override it by setting max_age to zero
            self.add_header('Cache-Control', 'max-age={}, public'.format(max_age))
            with open(filename) as f:
                yield from self._send_response_line()
                yield from self._send_headers()
                buf = bytearray(128)
                while True:
                    size = f.readinto(buf)
                    if size == 0:
                        break
                    yield from self.send(buf, sz=size)
        except OSError as e:
            raise HTTPException(404)


def restful_resource_handler(req, resp, param=None):
    """Handler for RESTful API endpoins"""
    # Gather data - query string, JSON in request body...
    data = yield from req.read_parse_form_data()
    # Add parameters from URI query string as well
    # This one is actually for simply development of RestAPI
    if req.query_string != b'':
        data.update(parse_query_string(req.query_string.decode()))
    # Call actual handler
    if param:
        res = req.params['_callmap'][req.method](data, param)
    else:
        res = req.params['_callmap'][req.method](data)
    # Handler result could be a tuple or just single dictionary, e.g.:
    # res = {'blah': 'blah'}
    # res = {'blah': 'blah'}, 201
    if type(res) == tuple:
        resp.code = res[1]
        res = res[0]
    elif res is None:
        raise Exception('Restful handler must return tuple/dict')

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
        Returns tuple of (function, opts, param) or (None, None) if not found.
        """
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
        """Handler for TCP connection with
        HTTP/1.0 protocol implementation
        """
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

            # OPTIONS method is handled automatically
            if req.method == b'OPTIONS':
                resp.add_access_control_headers()
                # Since we support only HTTP 1.0 - it is important
                # to tell browser that there is no payload expected
                # otherwise some webkit based browsers (Chrome)
                # treat this behavior as an error
                resp.add_header('Content-Length', '0')
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
        except OSError as e:
            # Do not send response in case of "Broken Pipe", its too late :)
            if e.args[0] != 32:
                yield from resp.error(500)
        except HTTPException as e:
            yield from resp.error(e.code)
        except Exception as e:
            yield from resp.error(500)
        finally:
            yield from writer.aclose()

    def add_route(self, url, f, **kwargs):
        """Add URL to function mapping.

        Arguments:
            url - url to map function with
            f - function to map

        Keyword arguments:
            methods - list of allowed methods. Defaults to ['GET', 'POST']
            parse_headers - turn on / off HTTP request header parsing. Default - True
            max_body_size - Max HTTP body size (e.g. POST form data). Defaults to 1024
            allowed_access_control_headers - Default value for the same name header. Defaults to *
            allowed_access_control_origins - Default value for the same name header. Defaults to *
        """
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
        params['allowed_access_control_methods'] = ', '.join(params['methods'])
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
        """Map resource (RestAPI) to URL

        Arguments:
            cls - Resource class to map to
            url - url to map to class

        Example:
            class myres():
                def get(self, data):
                    return {'hello': 'world'}


            app.add_resource(myres, '/api/myres')
        """
        methods = []
        callmap = {}
        # Create instance of resource handler, if passed as just class (not object)
        try:
            obj = cls()
        except TypeError:
            obj = cls
        # Get all implemented HTTP methods and make callmap
        for m in ['GET', 'POST', 'PUT', 'DELETE']:
            fn = m.lower()
            if hasattr(obj, fn):
                methods.append(m)
                callmap[m.encode()] = getattr(obj, fn)
        self.add_route(url, restful_resource_handler, methods=methods, _callmap=callmap)

    def route(self, url, **kwargs):
        """Decorator for add_route()

        Example:
            @app.route('/')
            def index(req, resp):
                yield from resp.start_html()
                yield from resp.send('<html><body><h1>Hello, world!</h1></html>\n')
        """
        def _route(f):
            self.add_route(url, f, **kwargs)
            return f
        return _route

    def run(self, host="127.0.0.1", port=8081, loop_forever=True, backlog=10):
        """Run Web Server. By default it runs forever.

        Keyword arguments:
            host - host to listen on. By default - localhost (127.0.0.1)
            port - port to listen on. By default - 8081
            loop_forever - run async.loop_forever(). Defaults to True
            backlog - size of pending connections queue. Defaults to 10
        """
        loop = asyncio.get_event_loop()
        print("* Starting Web Server at {}:{}".format(host, port))
        loop.create_task(asyncio.start_server(self._handler, host, port, backlog=backlog))
        if loop_forever:
            loop.run_forever()
            loop.close()
