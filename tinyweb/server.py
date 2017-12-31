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
                     405: 'Not Allowed',
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
        return '{} {:s} {:s}?{:s}\n{}'.format(self.__class__, self.method, self.path,
                                              self.query_string, str(self.headers))

    def read_request_line(self):
        """Read and parser HTTP RequestLine, e.g.:
            GET /something/script?param1=val1 HTTP/1.1
        """
        request_line = yield from self.reader.readline()
        if len(request_line.rstrip()) == 0:
            raise MalformedHTTP('EOF on request start')
        rl_frags = request_line.split()
        if len(rl_frags) != 3:
            raise MalformedHTTP('Malformed Request Line')
        self.method = rl_frags[0]
        url_frags = rl_frags[1].split(b'?', 1)
        self.path = url_frags[0]
        if len(url_frags) > 1:
            self.query_string = url_frags[1]

    def read_headers(self):
        """Reads and parses HTTP headers"""
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
        self.code = 200
        self.headers = {}

    def error(self, code, message=None):
        yield from self.writer.awrite('HTTP/1.0 {} {}\r\n\r\n'.
                                      format(code, http_status_codes[code]))
        if message:
            yield from self.writer.awrite(message)


class webserver:
    """Simple web server class"""

    def __init__(self):
        pass

    def _handler(self, reader, writer):
        """Handler for HTTP connection"""
        try:
            req = request(reader)
            resp = response(writer)
            yield from req.read_request_line()
            yield from req.read_headers()
            print(req)
        except MalformedHTTP as e:
            sys.print_exception(e)
            yield from resp.error(400)
        except Exception as e:
            yield from resp.error(500)
            sys.print_exception(e)
        finally:
            yield from writer.aclose()

    def run(self, host="127.0.0.1", port=8081, run_forever=True):
        loop = asyncio.get_event_loop()
        print("* Starting Web Server {}:{}".format(host, port))
        loop.create_task(asyncio.start_server(self._handler, host, port))
        if run_forever:
            loop.run_forever()
            loop.close()
