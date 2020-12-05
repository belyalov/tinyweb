#!/usr/bin/env micropython
"""
Unittests for Tiny Web
MIT license
(C) Konstantin Belyalov 2017-2018
"""

import unittest
import uos as os
import uerrno as errno
import uasyncio as asyncio
from tinyweb import webserver
from tinyweb.server import urldecode_plus, parse_query_string
from tinyweb.server import request, HTTPException


# Helper to delete file
def delete_file(fn):
    # "unlink" gets renamed to "remove" in micropython,
    # so support both
    if hasattr(os, 'unlink'):
        os.unlink(fn)
    else:
        os.remove(fn)


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

    async def readline(self):
        self.idx += 1
        # Convert and return str to bytes
        return self.lines[self.idx - 1].encode()

    def readexactly(self, n):
        return self.readline()


class mockWriter():
    """Mock for coroutine writer class"""

    def __init__(self, generate_expection=None):
        """
        keyword arguments:
            generate_expection - raise exception when calling send()
        """
        self.s = 1
        self.history = []
        self.closed = False
        self.generate_expection = generate_expection

    async def awrite(self, buf, off=0, sz=-1):
        if sz == -1:
            sz = len(buf) - off
        if self.generate_expection:
            raise self.generate_expection
        # Save biffer into history - so to be able to assert then
        self.history.append(buf[:sz])

    async def aclose(self):
        self.closed = True


async def mock_wait_for(coro, timeout):
    await coro


def run_coro(coro):
    # Mock wait_for() function with simple dummy
    asyncio.wait_for = (lambda c, t: await c)
    """Simple helper to run coroutine"""
    for i in coro:
        pass


# Tests

class Utils(unittest.TestCase):

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
                run_coro(req.read_request_line())
                self.assertEqual(r[1].encode(), req.method)
                self.assertEqual(r[2].encode(), req.path)
                if len(r) > 3:
                    self.assertEqual(r[3].encode(), req.query_string)
            except Exception:
                self.fail('exception on payload --{}--'.format(r[0]))

    def testRequestLineEmptyLinesBefore(self):
        req = request(mockReader(['\n', '\r\n', 'GET /?a=a HTTP/1.1']))
        run_coro(req.read_request_line())
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
                run_coro(req.read_request_line())

    def testHeadersSimple(self):
        req = request(mockReader([HDR('Host: google.com'),
                                  HDRE]))
        run_coro(req.read_headers([b'Host']))
        self.assertEqual(req.headers, {b'Host': b'google.com'})

    def testHeadersSpaces(self):
        req = request(mockReader([HDR('Host:    \t    google.com   \t     '),
                                  HDRE]))
        run_coro(req.read_headers([b'Host']))
        self.assertEqual(req.headers, {b'Host': b'google.com'})

    def testHeadersEmptyValue(self):
        req = request(mockReader([HDR('Host:'),
                                  HDRE]))
        run_coro(req.read_headers([b'Host']))
        self.assertEqual(req.headers, {b'Host': b''})

    def testHeadersMultiple(self):
        req = request(mockReader([HDR('Host: google.com'),
                                  HDR('Junk: you    blah'),
                                  HDR('Content-type:      file'),
                                  HDRE]))
        hdrs = {b'Host': b'google.com',
                b'Junk': b'you    blah',
                b'Content-type': b'file'}
        run_coro(req.read_headers([b'Host', b'Junk', b'Content-type']))
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


# We want to test decorators as well
server_for_decorators = webserver()


@server_for_decorators.route('/uid/<user_id>')
@server_for_decorators.route('/uid2/<user_id>')
async def route_for_decorator(req, resp, user_id):
    await resp.start_html()
    await resp.send('YO, {}'.format(user_id))


@server_for_decorators.resource('/rest1/<user_id>')
def resource_for_decorator1(data, user_id):
    return {'name': user_id}


@server_for_decorators.resource('/rest2/<user_id>')
async def resource_for_decorator2(data, user_id):
    yield '{"name": user_id}'


class ServerFull(unittest.TestCase):

    def setUp(self):
        self.dummy_called = False
        self.data = {}
        # "Register" one connection into map for dedicated decor server
        server_for_decorators.conns[id(1)] = None
        self.hello_world_history = ['HTTP/1.0 200 MSG\r\n' +
                                    'Content-Type: text/html\r\n\r\n',
                                    '<html><h1>Hello world</h1></html>']
        # Create one more server - to simplify bunch of tests
        self.srv = webserver()
        self.srv.conns[id(1)] = None

    def testRouteDecorator1(self):
        """Test @.route() decorator"""
        # First decorator
        rdr = mockReader(['GET /uid/man1 HTTP/1.1\r\n',
                          HDRE])
        wrt = mockWriter()
        # "Send" request
        run_coro(server_for_decorators._handler(rdr, wrt))
        # Ensure that proper response "sent"
        expected = ['HTTP/1.0 200 MSG\r\n' +
                    'Content-Type: text/html\r\n\r\n',
                    'YO, man1']
        self.assertEqual(wrt.history, expected)
        self.assertTrue(wrt.closed)

    def testRouteDecorator2(self):
        # Second decorator
        rdr = mockReader(['GET /uid2/man2 HTTP/1.1\r\n',
                          HDRE])
        wrt = mockWriter()
        # Re-register connection
        server_for_decorators.conns[id(1)] = None
        # "Send" request
        run_coro(server_for_decorators._handler(rdr, wrt))
        # Ensure that proper response "sent"
        expected = ['HTTP/1.0 200 MSG\r\n' +
                    'Content-Type: text/html\r\n\r\n',
                    'YO, man2']
        self.assertEqual(wrt.history, expected)
        self.assertTrue(wrt.closed)

    def testResourceDecorator1(self):
        """Test @.resource() decorator"""
        rdr = mockReader(['GET /rest1/man1 HTTP/1.1\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(server_for_decorators._handler(rdr, wrt))
        expected = ['HTTP/1.0 200 MSG\r\n'
                    'Access-Control-Allow-Origin: *\r\n' +
                    'Access-Control-Allow-Headers: *\r\n' +
                    'Content-Length: 16\r\n' +
                    'Access-Control-Allow-Methods: GET\r\n' +
                    'Content-Type: application/json\r\n\r\n',
                    '{"name": "man1"}']
        self.assertEqual(wrt.history, expected)
        self.assertTrue(wrt.closed)

    def testResourceDecorator2(self):
        rdr = mockReader(['GET /rest2/man2 HTTP/1.1\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(server_for_decorators._handler(rdr, wrt))
        expected = ['HTTP/1.1 200 MSG\r\n' +
                    'Access-Control-Allow-Methods: GET\r\n' +
                    'Connection: close\r\n' +
                    'Access-Control-Allow-Headers: *\r\n' +
                    'Content-Type: application/json\r\n' +
                    'Transfer-Encoding: chunked\r\n' +
                    'Access-Control-Allow-Origin: *\r\n\r\n',
                    '11\r\n',
                    '{"name": user_id}',
                    '\r\n',
                    '0\r\n\r\n'
                    ]
        self.assertEqual(wrt.history, expected)
        self.assertTrue(wrt.closed)

    def testCatchAllDecorator(self):
        # A fresh server for the catchall handler
        server_for_catchall_decorator = webserver()

        # Catchall decorator and handler
        @server_for_catchall_decorator.catchall()
        async def route_for_catchall_decorator(req, resp):
            await resp.start_html()
            await resp.send('my404')

        rdr = mockReader(['GET /this/is/an/invalid/url HTTP/1.1\r\n',
                          HDRE])
        wrt = mockWriter()
        server_for_catchall_decorator.conns[id(1)] = None
        run_coro(server_for_catchall_decorator._handler(rdr, wrt))
        expected = ['HTTP/1.0 200 MSG\r\n' +
                    'Content-Type: text/html\r\n\r\n',
                    'my404']
        self.assertEqual(wrt.history, expected)
        self.assertTrue(wrt.closed)

    async def dummy_handler(self, req, resp):
        """Dummy URL handler. It just records the fact - it has been called"""
        self.dummy_req = req
        self.dummy_resp = resp
        self.dummy_called = True

    async def dummy_post_handler(self, req, resp):
        self.data = await req.read_parse_form_data()

    async def hello_world_handler(self, req, resp):
        await resp.start_html()
        await resp.send('<html><h1>Hello world</h1></html>')

    async def redirect_handler(self, req, resp):
        await resp.redirect('/blahblah', msg='msg:)')

    def testStartHTML(self):
        """Verify that request.start_html() works well"""
        self.srv.add_route('/', self.hello_world_handler)
        rdr = mockReader(['GET / HTTP/1.1\r\n',
                          HDR('Host: blah.com'),
                          HDRE])
        wrt = mockWriter()
        # "Send" request
        run_coro(self.srv._handler(rdr, wrt))
        # Ensure that proper response "sent"
        self.assertEqual(wrt.history, self.hello_world_history)
        self.assertTrue(wrt.closed)

    def testRedirect(self):
        """Verify that request.start_html() works well"""
        self.srv.add_route('/', self.redirect_handler)
        rdr = mockReader(['GET / HTTP/1.1\r\n',
                          HDR('Host: blah.com'),
                          HDRE])
        wrt = mockWriter()
        # "Send" request
        run_coro(self.srv._handler(rdr, wrt))
        # Ensure that proper response "sent"
        exp = ['HTTP/1.0 302 MSG\r\n' +
               'Location: /blahblah\r\nContent-Length: 5\r\n\r\n',
               'msg:)']
        self.assertEqual(wrt.history, exp)

    def testRequestBodyUnknownType(self):
        """Unknow HTTP body test - empty dict expected"""
        self.srv.add_route('/', self.dummy_post_handler, methods=['POST'])
        rdr = mockReader(['POST / HTTP/1.1\r\n',
                          HDR('Host: blah.com'),
                          HDR('Content-Length: 5'),
                          HDRE,
                          '12345'])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        # Check extracted POST body
        self.assertEqual(self.data, {})

    def testRequestBodyJson(self):
        """JSON encoded POST body"""
        self.srv.add_route('/',
                           self.dummy_post_handler,
                           methods=['POST'],
                           save_headers=['Content-Type', 'Content-Length'])
        rdr = mockReader(['POST / HTTP/1.1\r\n',
                          HDR('Content-Type: application/json'),
                          HDR('Content-Length: 10'),
                          HDRE,
                          '{"a": "b"}'])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        # Check parsed POST body
        self.assertEqual(self.data, {'a': 'b'})

    def testRequestBodyUrlencoded(self):
        """Regular HTML form"""
        self.srv.add_route('/',
                           self.dummy_post_handler,
                           methods=['POST'],
                           save_headers=['Content-Type', 'Content-Length'])
        rdr = mockReader(['POST / HTTP/1.1\r\n',
                          HDR('Content-Type: application/x-www-form-urlencoded; charset=UTF-8'),
                          HDR('Content-Length: 10'),
                          HDRE,
                          'a=b&c=%20d'])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        # Check parsed POST body
        self.assertEqual(self.data, {'a': 'b', 'c': ' d'})

    def testRequestBodyNegative(self):
        """Regular HTML form"""
        self.srv.add_route('/',
                           self.dummy_post_handler,
                           methods=['POST'],
                           save_headers=['Content-Type', 'Content-Length'])
        rdr = mockReader(['POST / HTTP/1.1\r\n',
                          HDR('Content-Type: application/json'),
                          HDR('Content-Length: 9'),
                          HDRE,
                          'some junk'])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        # payload broken - HTTP 400 expected
        self.assertEqual(wrt.history, ['HTTP/1.0 400 MSG\r\n\r\n'])

    def testRequestLargeBody(self):
        """Max Body size check"""
        self.srv.add_route('/',
                           self.dummy_post_handler,
                           methods=['POST'],
                           save_headers=['Content-Type', 'Content-Length'],
                           max_body_size=5)
        rdr = mockReader(['POST / HTTP/1.1\r\n',
                          HDR('Content-Type: application/json'),
                          HDR('Content-Length: 9'),
                          HDRE,
                          'some junk'])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        # payload broken - HTTP 400 expected
        self.assertEqual(wrt.history, ['HTTP/1.0 413 MSG\r\n\r\n'])

    async def route_parameterized_handler(self, req, resp, user_name):
        await resp.start_html()
        await resp.send('<html>Hello, {}</html>'.format(user_name))

    def testRouteParameterized(self):
        """Verify that route with params works fine"""
        self.srv.add_route('/db/<user_name>', self.route_parameterized_handler)
        rdr = mockReader(['GET /db/user1 HTTP/1.1\r\n',
                          HDR('Host: junk.com'),
                          HDRE])
        wrt = mockWriter()
        # "Send" request
        run_coro(self.srv._handler(rdr, wrt))
        # Ensure that proper response "sent"
        expected = ['HTTP/1.0 200 MSG\r\n' +
                    'Content-Type: text/html\r\n\r\n',
                    '<html>Hello, user1</html>']
        self.assertEqual(wrt.history, expected)
        self.assertTrue(wrt.closed)

    def testParseHeadersOnOff(self):
        """Verify parameter parse_headers works"""
        self.srv.add_route('/', self.dummy_handler, save_headers=['H1', 'H2'])
        rdr = mockReader(['GET / HTTP/1.1\r\n',
                          HDR('H1: blah.com'),
                          HDR('H2: lalalla'),
                          HDR('Junk: fsdfmsdjfgjsdfjunk.com'),
                          HDRE])
        # "Send" request
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        self.assertTrue(self.dummy_called)
        # Check for headers - only 2 of 3 should be collected, others - ignore
        hdrs = {b'H1': b'blah.com',
                b'H2': b'lalalla'}
        self.assertEqual(self.dummy_req.headers, hdrs)
        self.assertTrue(wrt.closed)

    def testDisallowedMethod(self):
        """Verify that server respects allowed methods"""
        self.srv.add_route('/', self.hello_world_handler)
        self.srv.add_route('/post_only', self.dummy_handler, methods=['POST'])
        rdr = mockReader(['GET / HTTP/1.0\r\n',
                          HDRE])
        # "Send" GET request, by default GET is enabled
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        self.assertEqual(wrt.history, self.hello_world_history)
        self.assertTrue(wrt.closed)

        # "Send" GET request to POST only location
        self.srv.conns[id(1)] = None
        self.dummy_called = False
        rdr = mockReader(['GET /post_only HTTP/1.1\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        # Hanlder should not be called - method not allowed
        self.assertFalse(self.dummy_called)
        exp = ['HTTP/1.0 405 MSG\r\n\r\n']
        self.assertEqual(wrt.history, exp)
        # Connection must be closed
        self.assertTrue(wrt.closed)

    def testAutoOptionsMethod(self):
        """Test auto implementation of OPTIONS method"""
        self.srv.add_route('/', self.hello_world_handler, methods=['POST', 'PUT', 'DELETE'])
        self.srv.add_route('/disabled', self.hello_world_handler, auto_method_options=False)
        rdr = mockReader(['OPTIONS / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))

        exp = ['HTTP/1.0 200 MSG\r\n' +
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
        run_coro(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 404 MSG\r\n\r\n']
        self.assertEqual(wrt.history, exp)
        # Connection must be closed
        self.assertTrue(wrt.closed)

    def testMalformedRequest(self):
        """Verify that malformed request generates proper response"""
        rdr = mockReader(['GET /\r\n',
                          HDR('Host: blah.com'),
                          HDRE])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 400 MSG\r\n\r\n']
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


class ResourceGetArgs():
    """REST API resource with additional arguments"""

    def get(self, data, arg1, arg2):
        return {'arg1': arg1, 'arg2': arg2}


class ResourceGenerator():
    """REST API with generator as result"""

    async def get(self, data):
        yield 'longlongchunkchunk1'
        yield 'chunk2'
        # unicode support
        yield '\u265E'


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
        self.srv.conns[id(1)] = None
        self.srv.add_resource(ResourceGetPost, '/')
        self.srv.add_resource(ResourceGetParam, '/param/<user_id>')
        self.srv.add_resource(ResourceGetArgs, '/args', arg1=1, arg2=2)
        self.srv.add_resource(ResourceGenerator, '/gen')
        self.srv.add_resource(ResourceNegative, '/negative')

    def testOptions(self):
        # Ensure that only GET/POST methods are allowed:
        rdr = mockReader(['OPTIONS / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 200 MSG\r\n' +
               'Access-Control-Allow-Headers: *\r\n'
               'Content-Length: 0\r\n'
               'Access-Control-Allow-Origin: *\r\n'
               'Access-Control-Allow-Methods: GET, POST\r\n\r\n']
        self.assertEqual(wrt.history, exp)

    def testGet(self):
        rdr = mockReader(['GET / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 200 MSG\r\n' +
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
        run_coro(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 200 MSG\r\n' +
               'Access-Control-Allow-Origin: *\r\n'
               'Access-Control-Allow-Headers: *\r\n'
               'Content-Length: 18\r\n'
               'Access-Control-Allow-Methods: GET\r\n'
               'Content-Type: application/json\r\n\r\n',
               '{"user_id": "123"}']
        self.assertEqual(wrt.history, exp)

    def testGetWithArgs(self):
        rdr = mockReader(['GET /args HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 200 MSG\r\n' +
               'Access-Control-Allow-Origin: *\r\n'
               'Access-Control-Allow-Headers: *\r\n'
               'Content-Length: 22\r\n'
               'Access-Control-Allow-Methods: GET\r\n'
               'Content-Type: application/json\r\n\r\n',
               '{"arg1": 1, "arg2": 2}']
        self.assertEqual(wrt.history, exp)

    def testGenerator(self):
        rdr = mockReader(['GET /gen HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.1 200 MSG\r\n' +
               'Access-Control-Allow-Methods: GET\r\n' +
               'Connection: close\r\n' +
               'Access-Control-Allow-Headers: *\r\n' +
               'Content-Type: application/json\r\n' +
               'Transfer-Encoding: chunked\r\n' +
               'Access-Control-Allow-Origin: *\r\n\r\n',
               '13\r\n',
               'longlongchunkchunk1',
               '\r\n',
               '6\r\n',
               'chunk2',
               '\r\n',
               # next chunk is 1 char len UTF-8 string
               '3\r\n',
               '\u265E',
               '\r\n',
               '0\r\n\r\n']
        self.assertEqual(wrt.history, exp)

    def testPost(self):
        # Ensure that parameters from query string / body will be combined as well
        rdr = mockReader(['POST /?qs=qs1 HTTP/1.0\r\n',
                          HDR('Content-Length: 17'),
                          HDR('Content-Type: application/json'),
                          HDRE,
                          '{"body": "body1"}'])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 200 MSG\r\n' +
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
        run_coro(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 405 MSG\r\n\r\n']
        self.assertEqual(wrt.history, exp)

    def testException(self):
        rdr = mockReader(['PUT /negative HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 500 MSG\r\n\r\n']
        self.assertEqual(wrt.history, exp)

    def testBrokenPipe(self):
        rdr = mockReader(['DELETE /negative HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))
        self.assertEqual(wrt.history, [])


class StaticContent(unittest.TestCase):

    def setUp(self):
        self.srv = webserver()
        self.srv.conns[id(1)] = None
        self.tempfn = '__tmp.html'
        self.ctype = None
        self.etype = None
        self.max_age = 2592000
        with open(self.tempfn, 'wb') as f:
            f.write('someContent blah blah')

    def tearDown(self):
        try:
            delete_file(self.tempfn)
        except OSError:
            pass

    async def send_file_handler(self, req, resp):
        await resp.send_file(self.tempfn,
                             content_type=self.ctype,
                             content_encoding=self.etype,
                             max_age=self.max_age)

    def testSendFileManual(self):
        """Verify send_file works great with manually defined parameters"""
        self.ctype = 'text/plain'
        self.etype = 'gzip'
        self.max_age = 100
        self.srv.add_route('/', self.send_file_handler)
        rdr = mockReader(['GET / HTTP/1.0\r\n',
                          HDRE])
        wrt = mockWriter()
        run_coro(self.srv._handler(rdr, wrt))

        exp = ['HTTP/1.0 200 MSG\r\n' +
               'Cache-Control: max-age=100, public\r\n'
               'Content-Type: text/plain\r\n'
               'Content-Length: 21\r\n'
               'Content-Encoding: gzip\r\n\r\n',
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
        delete_file(self.tempfn)
        run_coro(self.srv._handler(rdr, wrt))

        exp = ['HTTP/1.0 404 MSG\r\n\r\n']
        self.assertEqual(wrt.history, exp)
        self.assertTrue(wrt.closed)

    def testSendFileConnectionReset(self):
        self.srv.add_route('/', self.send_file_handler)
        rdr = mockReader(['GET / HTTP/1.0\r\n',
                          HDRE])
        # tell mockWrite to raise error during send()
        wrt = mockWriter(generate_expection=OSError(errno.ECONNRESET))

        run_coro(self.srv._handler(rdr, wrt))

        # there should be no payload due to connected reset
        self.assertEqual(wrt.history, [])
        self.assertTrue(wrt.closed)


if __name__ == '__main__':
    unittest.main()
