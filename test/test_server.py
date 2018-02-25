#!/usr/bin/env micropython
"""
Unittests for Tiny Web
MIT license
(C) Konstantin Belyalov 2017-2018
"""

import unittest
import os
from tinyweb import webserver
from tinyweb.server import get_file_mime_type, urldecode_plus, parse_query_string
from tinyweb.server import request, HTTPException


# Helpers

# HTTP headers helpers


def HDR(str):
    return '{}\r\n'.format(str)


HDRE = '\r\n'


class mockReader():
    """Mock for coroutine reader class"""

    def __init__(self, lines):
        if type(lines) is not list:
            lines = [lines]
        self.lines = lines
        self.idx = 0

    def readline(self):
        # Make this function to be as generator
        yield
        self.idx += 1
        # Convert and return str to bytes
        return self.lines[self.idx - 1].encode()

    def readexactly(self, n):
        return self.readline()


class mockWriter():
    """Mock for coroutine writer class"""

    def __init__(self):
        self.history = []
        self.closed = False

    def awrite(self, buf, off=0, sz=-1):
        if sz == -1:
            sz = len(buf) - off
        # Make this function to be as generator
        yield
        # Save biffer into history - so to be able to assert then
        self.history.append(buf[:sz])

    def aclose(self):
        yield
        self.closed = True


def run_generator(gen):
    """Simple helper to run generator"""
    for i in gen:
        pass


# Tests

class Utils(unittest.TestCase):

    def testMimeTypes(self):
        self.assertEqual(get_file_mime_type('a.html'), 'text/html')
        self.assertEqual(get_file_mime_type('a.gif'), 'image/gif')

    def testMimeTypesUnknown(self):
        runs = ['', '.', 'bbb', 'bbb.bbbb', '/', ' ']
        for r in runs:
            self.assertEqual('text/plain', get_file_mime_type(r))

    def testUrldecode(self):
        runs = [('abc%20def', 'abc def'),
                ('abc%%20def', 'abc% def'),
                ('%%%', '%%%'),
                ('%20%20', '  '),
                ('abc', 'abc'),
                ('a%25%25%25c', 'a%%%c'),
                ('a++b', 'a  b'),
                ('+%25+', ' % '),
                ('+%2B+', ' + '),
                ('%20+%2B+%41', '  + A'),
                ]

        for r in runs:
            self.assertEqual(urldecode_plus(r[0]), r[1])

    def testParseQueryString(self):
        runs = [('k1=v2', {'k1': 'v2'}),
                ('k1=v2&k11=v11', {'k1': 'v2',
                                   'k11': 'v11'}),
                ('k1=v2&k11=', {'k1': 'v2',
                                'k11': ''}),
                ('k1=+%20', {'k1': '  '}),
                ('%6b1=+%20', {'k1': '  '}),
                ('k1=%3d1', {'k1': '=1'}),
                ('11=22%26&%3d=%3d', {'11': '22&',
                                      '=': '='}),
                ]
        for r in runs:
            self.assertEqual(parse_query_string(r[0]), r[1])


class ServerParts(unittest.TestCase):

    def testRequestLine(self):
        runs = [('GETT / HTTP/1.1', 'GETT', '/'),
                ('TTEG\t/blah\tHTTP/1.1', 'TTEG', '/blah'),
                ('POST /qq/?q=q HTTP', 'POST', '/qq/', 'q=q'),
                ('POST /?q=q BSHT', 'POST', '/', 'q=q'),
                ('POST /?q=q&a=a JUNK', 'POST', '/', 'q=q&a=a')]

        for r in runs:
            try:
                req = request(mockReader(r[0]))
                run_generator(req.read_request_line())
                self.assertEqual(r[1].encode(), req.method)
                self.assertEqual(r[2].encode(), req.path)
                if len(r) > 3:
                    self.assertEqual(r[3].encode(), req.query_string)
            except Exception:
                self.fail('exception on payload --{}--'.format(r[0]))

    def testRequestLineEmptyLinesBefore(self):
        req = request(mockReader(['\n', '\r\n', 'GET /?a=a HTTP/1.1']))
        run_generator(req.read_request_line())
        self.assertEqual(b'GET', req.method)
        self.assertEqual(b'/', req.path)
        self.assertEqual(b'a=a', req.query_string)

    def testRequestLineNegative(self):
        runs = ['',
                '\t\t',
                '  ',
                ' / HTTP/1.1',
                'GET',
                'GET /',
                'GET / '
                ]

        for r in runs:
            with self.assertRaises(HTTPException):
                req = request(mockReader(r))
                run_generator(req.read_request_line())

    def testHeadersSimple(self):
        req = request(mockReader([HDR('Host: google.com'),
                                  HDRE]))
        run_generator(req.read_headers())
        self.assertEqual(req.headers, {b'Host': b'google.com'})

    def testHeadersSpaces(self):
        req = request(mockReader([HDR('Host:    \t    google.com   \t     '),
                                  HDRE]))
        run_generator(req.read_headers())
        self.assertEqual(req.headers, {b'Host': b'google.com'})

    def testHeadersEmptyValue(self):
        req = request(mockReader([HDR('Host:'),
                                  HDRE]))
        run_generator(req.read_headers())
        self.assertEqual(req.headers, {b'Host': b''})

    def testHeadersMultiple(self):
        req = request(mockReader([HDR('Host: google.com'),
                                  HDR('Junk: you    blah'),
                                  HDR('Content-type:      file'),
                                  HDRE]))
        hdrs = {b'Host': b'google.com',
                b'Junk': b'you    blah',
                b'Content-type': b'file'}
        run_generator(req.read_headers())
        self.assertEqual(req.headers, hdrs)

    def testUrlFinderExplicit(self):
        urls = [('/', 1),
                ('/%20', 2),
                ('/a/b', 3),
                ('/aac', 5)]
        junk = ['//', '', '/a', '/aa', '/a/fhhfhfhfhfhf']
        # Create server, add routes
        srv = webserver()
        for u in urls:
            srv.add_route(u[0], u[1])
        # Search them all
        for u in urls:
            # Create mock request object with "pre-parsed" url path
            rq = request(mockReader([]))
            rq.path = u[0].encode()
            f, args = srv._find_url_handler(rq)
            self.assertEqual(u[1], f)
        # Some simple negative cases
        for j in junk:
            rq = request(mockReader([]))
            rq.path = j.encode()
            f, args = srv._find_url_handler(rq)
            self.assertIsNone(f)
            self.assertIsNone(args)

    def testUrlFinderParameterized(self):
        srv = webserver()
        # Add few routes
        srv.add_route('/', 0)
        srv.add_route('/<user_name>', 1)
        srv.add_route('/a/<id>', 2)
        # Check first url (non param)
        rq = request(mockReader([]))
        rq.path = b'/'
        f, args = srv._find_url_handler(rq)
        self.assertEqual(f, 0)
        # Check second url
        rq.path = b'/user1'
        f, args = srv._find_url_handler(rq)
        self.assertEqual(f, 1)
        self.assertEqual(args['_param_name'], 'user_name')
        self.assertEqual(rq._param, 'user1')
        # Check third url
        rq.path = b'/a/123456'
        f, args = srv._find_url_handler(rq)
        self.assertEqual(f, 2)
        self.assertEqual(args['_param_name'], 'id')
        self.assertEqual(rq._param, '123456')
        # When param is empty and there is no non param endpoint
        rq.path = b'/a/'
        f, args = srv._find_url_handler(rq)
        self.assertEqual(f, 2)
        self.assertEqual(rq._param, '')

    def testUrlFinderNegative(self):
        srv = webserver()
        # empty URL is not allowed
        with self.assertRaises(ValueError):
            srv.add_route('', 1)
        # Query string is not allowed
        with self.assertRaises(ValueError):
            srv.add_route('/?a=a', 1)
        # Duplicate urls
        srv.add_route('/duppp', 1)
        with self.assertRaises(ValueError):
            srv.add_route('/duppp', 1)


# We want to test decorator @server.route as well
server_for_decorators = webserver()


@server_for_decorators.route('/uid/<user_id>')
@server_for_decorators.route('/uid2/<user_id>')
def route_for_decorator(req, resp, user_id):
    yield from resp.start_html()
    yield from resp.send('YO, {}'.format(user_id))


class ServerFull(unittest.TestCase):

    def setUp(self):
        self.dummy_called = False
        self.data = {}
        self.hello_world_history = ['HTTP/1.0 200 OK\r\n',
                                    'Content-Type: text/html\r\n\r\n',
                                    '<html><h1>Hello world</h1></html>']

    def testDecorator(self):
        """Test @.route() decorator"""
        # First decorator
        rdr = mockReader(['GET /uid/man1 HTTP/1.1\r\n',
                          HDRE])
        wrt = mockWriter()
        # "Send" request
        run_generator(server_for_decorators._handler(rdr, wrt))
        # Ensure that proper response "sent"
        expected = ['HTTP/1.0 200 OK\r\n',
                    'Content-Type: text/html\r\n\r\n',
                    'YO, man1']
        self.assertEqual(wrt.history, expected)
        self.assertTrue(wrt.closed)

        # Second decorator
        rdr = mockReader(['GET /uid2/man2 HTTP/1.1\r\n',
                          HDRE])
        wrt = mockWriter()
        # "Send" request
        run_generator(server_for_decorators._handler(rdr, wrt))
        # Ensure that proper response "sent"
        expected = ['HTTP/1.0 200 OK\r\n',
                    'Content-Type: text/html\r\n\r\n',
                    'YO, man2']
        self.assertEqual(wrt.history, expected)
        self.assertTrue(wrt.closed)

    def dummy_handler(self, req, resp):
        """Dummy URL handler. It just records the fact - it has been called"""
        self.dummy_req = req
        self.dummy_resp = resp
        self.dummy_called = True
        yield

    def dummy_post_handler(self, req, resp):
        self.data = yield from req.read_parse_form_data()

    def hello_world_handler(self, req, resp):
        yield from resp.start_html()
        yield from resp.send('<html><h1>Hello world</h1></html>')

    def redirect_handler(self, req, resp):
        yield from resp.redirect('/blahblah')

    def testStartHTML(self):
        """Verify that request.start_html() works well"""
        srv = webserver()
        srv.add_route('/', self.hello_world_handler)
        rdr = mockReader(['GET / HTTP/1.1\r\n',
                          HDR('Host: blah.com'),
                          HDRE])
        wrt = mockWriter()
        # "Send" request
        run_generator(srv._handler(rdr, wrt))
        # Ensure that proper response "sent"
        self.assertEqual(wrt.history, self.hello_world_history)
        self.assertTrue(wrt.closed)

    def testRedirect(self):
        """Verify that request.start_html() works well"""
        srv = webserver()
        srv.add_route('/', self.redirect_handler)
        rdr = mockReader(['GET / HTTP/1.1\r\n',
                          HDR('Host: blah.com'),
                          HDRE])
        wrt = mockWriter()
        # "Send" request
        run_generator(srv._handler(rdr, wrt))
        # Ensure that proper response "sent"
        self.assertEqual(wrt.history, ['HTTP/1.0 302 Found\r\n', 'Location: /blahblah\r\n\r\n'])

    def testRequestBodyUnknownType(self):
        """Unknow HTTP body test - empty dict expected"""
        srv = webserver()
        srv.add_route('/', self.dummy_post_handler, methods=['POST'])
        rdr = mockReader(['POST / HTTP/1.1\r\n',
                          HDR('Host: blah.com'),
                          HDR('Content-Length: 5'),
                          HDRE,
                          '12345'])
        wrt = mockWriter()
        run_generator(srv._handler(rdr, wrt))
        # Check extracted POST body
        self.assertEqual(self.data, {})

    def testRequestBodyJson(self):
        """JSON encoded POST body"""
        srv = webserver()
        srv.add_route('/', self.dummy_post_handler, methods=['POST'])
        rdr = mockReader(['POST / HTTP/1.1\r\n',
                          HDR('Content-Type: application/json'),
                          HDR('Content-Length: 10'),
                          HDRE,
                          '{"a": "b"}'])
        wrt = mockWriter()
        run_generator(srv._handler(rdr, wrt))
        # Check parsed POST body
        self.assertEqual(self.data, {'a': 'b'})

    def testRequestBodyUrlencoded(self):
        """Regular HTML form"""
        srv = webserver()
        srv.add_route('/', self.dummy_post_handler, methods=['POST'])
        rdr = mockReader(['POST / HTTP/1.1\r\n',
                          HDR('Content-Type: application/x-www-form-urlencoded; charset=UTF-8'),
                          HDR('Content-Length: 10'),
                          HDRE,
                          'a=b&c=%20d'])
        wrt = mockWriter()
        run_generator(srv._handler(rdr, wrt))
        # Check parsed POST body
        self.assertEqual(self.data, {'a': 'b', 'c': ' d'})

    def testRequestBodyNegative(self):
        """Regular HTML form"""
        srv = webserver()
        srv.add_route('/', self.dummy_post_handler, methods=['POST'])
        rdr = mockReader(['POST / HTTP/1.1\r\n',
                          HDR('Content-Type: application/json'),
                          HDR('Content-Length: 9'),
                          HDRE,
                          'some junk'])
        wrt = mockWriter()
        run_generator(srv._handler(rdr, wrt))
        # payload broken - HTTP 400 expected
        self.assertEqual(wrt.history, ['HTTP/1.0 400 Bad Request\r\n', '\r\n'])

    def testRequestLargeBody(self):
        """Max Body size check"""
        srv = webserver()
        srv.add_route('/', self.dummy_post_handler, methods=['POST'], max_body_size=5)
        rdr = mockReader(['POST / HTTP/1.1\r\n',
                          HDR('Content-Type: application/json'),
                          HDR('Content-Length: 9'),
                          HDRE,
                          'some junk'])
        wrt = mockWriter()
        run_generator(srv._handler(rdr, wrt))
        # payload broken - HTTP 400 expected
        self.assertEqual(wrt.history, ['HTTP/1.0 413 Payload Too Large\r\n', '\r\n'])

    def route_parameterized_handler(self, req, resp, user_name):
        yield from resp.start_html()
        yield from resp.send('<html>Hello, {}</html>'.format(user_name))

    def testRouteParameterized(self):
        """Verify that route with params works fine"""
        srv = webserver()
        srv.add_route('/db/<user_name>', self.route_parameterized_handler)
        rdr = mockReader(['GET /db/user1 HTTP/1.1\r\n',
                          HDR('Host: junk.com'),
                          HDRE])
        wrt = mockWriter()
        # "Send" request
        run_generator(srv._handler(rdr, wrt))
        # Ensure that proper response "sent"
        expected = ['HTTP/1.0 200 OK\r\n',
                    'Content-Type: text/html\r\n\r\n',
                    '<html>Hello, user1</html>']
        self.assertEqual(wrt.history, expected)
        self.assertTrue(wrt.closed)

    def testParseHeadersOnOff(self):
        """Verify parameter parse_headers works"""
        srv = webserver()
        srv.add_route('/parse', self.dummy_handler, parse_headers=True)
        srv.add_route('/noparse', self.dummy_handler, parse_headers=False)
        rdr = mockReader(['GET /noparse HTTP/1.1\r\n',
                          HDR('Host: blah.com'),
                          HDR('Header1: lalalla'),
                          HDR('Junk: junk.com'),
                          HDRE])
        # "Send" request with parsing off
        wrt = mockWriter()
        run_generator(srv._handler(rdr, wrt))
        self.assertTrue(self.dummy_called)
        # Check for headers
        self.assertEqual(self.dummy_req.headers, {})
        self.assertTrue(wrt.closed)

        # "Send" request with parsing on
        rdr = mockReader(['GET /parse HTTP/1.1\r\n',
                          HDR('Host: blah.com'),
                          HDR('Header1: lalalla'),
                          HDR('Junk: junk.com'),
                          HDRE])
        wrt = mockWriter()
        run_generator(srv._handler(rdr, wrt))
        self.assertTrue(self.dummy_called)
        # Check for headers
        hdrs = {b'Junk': b'junk.com',
                b'Host': b'blah.com',
                b'Header1': b'lalalla'}
        self.assertEqual(self.dummy_req.headers, hdrs)
        self.assertTrue(wrt.closed)

    def testDisallowedMethod(self):
        """Verify that server respects allowed methods"""
        srv = webserver()
        srv.add_route('/', self.hello_world_handler)
        srv.add_route('/post_only', self.dummy_handler, methods=['POST'])
        rdr = mockReader(['GET / HTTP/1.0\r\n',
                          HDRE])
        # "Send" GET request, by default GET is enabled
        wrt = mockWriter()
        run_generator(srv._handler(rdr, wrt))
        self.assertEqual(wrt.history, self.hello_world_history)
        self.assertTrue(wrt.closed)

        # "Send" GET request to POST only location
        self.dummy_called = False
        rdr = mockReader(['GET /post_only HTTP/1.1\r\n',
                          HDRE])
        wrt = mockWriter()
        run_generator(srv._handler(rdr, wrt))
        # Hanlder should not be called - method not allowed
        self.assertFalse(self.dummy_called)
        exp = ['HTTP/1.0 405 Method Not Allowed\r\n',
               '\r\n']
        self.assertEqual(wrt.history, exp)
        # Connection must be closed
        self.assertTrue(wrt.closed)

    def testAutoOptionsMethod(self):
        """Test auto implementation of OPTIONS method"""
        srv = webserver()
        srv.add_route('/', self.hello_world_handler, methods=['POST', 'PUT', 'DELETE'])
        srv.add_route('/disabled', self.hello_world_handler, auto_method_options=False)
        rdr = mockReader(['OPTIONS / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_generator(srv._handler(rdr, wrt))

        exp = ['HTTP/1.0 200 OK\r\n',
               'Access-Control-Allow-Headers: *\r\n'
               'Content-Length: 0\r\n'
               'Access-Control-Allow-Origin: *\r\n'
               'Access-Control-Allow-Methods: POST, PUT, DELETE\r\n\r\n']
        self.assertEqual(wrt.history, exp)
        self.assertTrue(wrt.closed)

    def testPageNotFound(self):
        """Verify that malformed request generates proper response"""
        rdr = mockReader(['GET /not_existing HTTP/1.1\r\n',
                          HDR('Host: blah.com'),
                          HDRE])
        wrt = mockWriter()
        srv = webserver()
        run_generator(srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 404 Not Found\r\n',
               'Content-Length: 14\r\n\r\n',
               'Page Not Found']
        self.assertEqual(wrt.history, exp)
        # Connection must be closed
        self.assertTrue(wrt.closed)

    def testMalformedRequest(self):
        """Verify that malformed request generates proper response"""
        rdr = mockReader(['GET /\r\n',
                          HDR('Host: blah.com'),
                          HDRE])
        wrt = mockWriter()
        srv = webserver()
        run_generator(srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 400 Bad Request\r\n',
               '\r\n']
        self.assertEqual(wrt.history, exp)
        # Connection must be closed
        self.assertTrue(wrt.closed)


class ResourceGetPost():
    """Simple REST API resource class with just two methods"""

    def get(self, data):
        return {'data1': 'junk'}

    def post(self, data):
        return data


class ResourceGetParam():
    """Parameterized REST API resource"""

    def __init__(self):
        self.user_id = 'user_id'

    def get(self, data, user_id):
        return {self.user_id: user_id}


class ResourceNegative():
    """To cover negative test cases"""

    def delete(self, data):
        # Broken pipe emulation
        raise OSError(32, '', '')

    def put(self, data):
        # Simple unhandled expection
        raise Exception('something')


class ServerResource(unittest.TestCase):

    def setUp(self):
        self.srv = webserver()
        self.srv.add_resource(ResourceGetPost, '/')
        self.srv.add_resource(ResourceGetParam, '/param/<user_id>')
        self.srv.add_resource(ResourceNegative, '/negative')

    def testOptions(self):
        # Ensure that only GET/POST methods are allowed:
        rdr = mockReader(['OPTIONS / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_generator(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 200 OK\r\n',
               'Access-Control-Allow-Headers: *\r\n'
               'Content-Length: 0\r\n'
               'Access-Control-Allow-Origin: *\r\n'
               'Access-Control-Allow-Methods: GET, POST\r\n\r\n']
        self.assertEqual(wrt.history, exp)

    def testGet(self):
        rdr = mockReader(['GET / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_generator(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 200 OK\r\n',
               'Access-Control-Allow-Origin: *\r\n'
               'Access-Control-Allow-Headers: *\r\n'
               'Content-Length: 17\r\n'
               'Access-Control-Allow-Methods: GET, POST\r\n'
               'Content-Type: application/json\r\n\r\n',
               '{"data1": "junk"}']
        self.assertEqual(wrt.history, exp)

    def testGetWithParam(self):
        rdr = mockReader(['GET /param/123 HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_generator(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 200 OK\r\n',
               'Access-Control-Allow-Origin: *\r\n'
               'Access-Control-Allow-Headers: *\r\n'
               'Content-Length: 18\r\n'
               'Access-Control-Allow-Methods: GET\r\n'
               'Content-Type: application/json\r\n\r\n',
               '{"user_id": "123"}']
        self.assertEqual(wrt.history, exp)

    def testPost(self):
        # Ensure that parameters from query string / body will be combined as well
        rdr = mockReader(['POST /?qs=qs1 HTTP/1.0\r\n',
                          HDR('Content-Length: 17'),
                          HDR('Content-Type: application/json'),
                          HDRE,
                          '{"body": "body1"}'])
        wrt = mockWriter()
        run_generator(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 200 OK\r\n',
               'Access-Control-Allow-Origin: *\r\n'
               'Access-Control-Allow-Headers: *\r\n'
               'Content-Length: 30\r\n'
               'Access-Control-Allow-Methods: GET, POST\r\n'
               'Content-Type: application/json\r\n\r\n',
               '{"qs": "qs1", "body": "body1"}']
        self.assertEqual(wrt.history, exp)

    def testInvalidMethod(self):
        rdr = mockReader(['PUT / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_generator(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 405 Method Not Allowed\r\n',
               '\r\n']
        self.assertEqual(wrt.history, exp)

    def testException(self):
        rdr = mockReader(['PUT /negative HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_generator(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 500 Internal Server Error\r\n',
               '\r\n']
        self.assertEqual(wrt.history, exp)

    def testBrokenPipe(self):
        rdr = mockReader(['DELETE /negative HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_generator(self.srv._handler(rdr, wrt))
        self.assertEqual(wrt.history, [])


class StaticContent(unittest.TestCase):

    def setUp(self):
        self.srv = webserver()
        self.tempfn = '__tmp.html'
        self.ctype = None
        self.max_age = 2592000
        with open(self.tempfn, 'wb') as f:
            f.write('someContent blah blah')

    def tearDown(self):
        try:
            os.remove(self.tempfn)
        except OSError:
            pass

    def send_file_handler(self, req, resp):
        yield from resp.send_file(self.tempfn, content_type=self.ctype,
                                  max_age=self.max_age)

    def testSendFileAutoMime(self):
        """Verify send_file feature with auto mime type"""
        self.srv.add_route('/', self.send_file_handler)
        rdr = mockReader(['GET / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_generator(self.srv._handler(rdr, wrt))

        exp = ['HTTP/1.0 200 OK\r\n',
               'Content-Type: text/html\r\n'
               'Content-Length: 21\r\n'
               'Cache-Control: max-age=2592000, public\r\n\r\n',
               bytearray(b'someContent blah blah')]
        self.assertEqual(wrt.history, exp)
        self.assertTrue(wrt.closed)

    def testSendFileManual(self):
        """Verify send_file feature with auto mime type"""
        self.ctype = 'text/plain'
        self.max_age = 100
        self.srv.add_route('/', self.send_file_handler)
        rdr = mockReader(['GET / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_generator(self.srv._handler(rdr, wrt))

        exp = ['HTTP/1.0 200 OK\r\n',
               'Content-Type: text/plain\r\n'
               'Content-Length: 21\r\n'
               'Cache-Control: max-age=100, public\r\n\r\n',
               bytearray(b'someContent blah blah')]
        self.assertEqual(wrt.history, exp)
        self.assertTrue(wrt.closed)

    def testSendFileNotFound(self):
        """Verify 404 error for non existing files"""
        self.srv.add_route('/', self.send_file_handler)
        rdr = mockReader(['GET / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()

        # Intentionally delete file before request
        os.remove(self.tempfn)
        run_generator(self.srv._handler(rdr, wrt))

        exp = ['HTTP/1.0 404 Not Found\r\n',
               'Content-Length: 14\r\n\r\n',
               'File Not Found']
        self.assertEqual(wrt.history, exp)
        self.assertTrue(wrt.closed)


if __name__ == '__main__':
    unittest.main()
