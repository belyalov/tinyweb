"""
Unittests for Tiny Web
MIT license
"""

import unittest
import tinyweb.server as server

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


class mockWriter():
    """Mock for coroutine writer class"""

    def __init__(self):
        self.history = []
        self.closed = False

    def awrite(self, buf, off=0, sz=-1):
        # Make this function to be as generator
        yield
        # Save biffer into history - so to be able to assert then
        self.history.append(buf)

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
        for ext, mime in server.mime_types.items():
            res = server.get_file_mime_type('aaa' + ext)
            self.assertEqual(res, mime)

    def testMimeTypesUnknown(self):
        runs = ['', '.', 'bbb', 'bbb.bbbb', '/', ' ']
        for r in runs:
            self.assertEqual('text/plain', server.get_file_mime_type(r))


class ServerParts(unittest.TestCase):

    def testRequestLine(self):
        runs = [('GETT / HTTP/1.1', 'GETT', '/'),
                ('TTEG\t/blah\tHTTP/1.1', 'TTEG', '/blah'),
                ('POST /qq/?q=q HTTP', 'POST', '/qq/', 'q=q'),
                ('POST /?q=q BSHT', 'POST', '/', 'q=q'),
                ('POST /?q=q&a=a JUNK', 'POST', '/', 'q=q&a=a')]

        for r in runs:
            try:
                req = server.request(mockReader(r[0]))
                run_generator(req.read_request_line())
                self.assertEqual(r[1].encode(), req.method)
                self.assertEqual(r[2].encode(), req.path)
                if len(r) > 3:
                    self.assertEqual(r[3].encode(), req.query_string)
            except Exception:
                self.fail('exception on payload --{}--'.format(r[0]))

    def testRequestLineEmptyLinesBefore(self):
        req = server.request(mockReader(['\n', '\r\n', 'GET /?a=a HTTP/1.1']))
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
            with self.assertRaises(server.MalformedHTTP):
                req = server.request(mockReader(r))
                run_generator(req.read_request_line())

    def testHeadersSimple(self):
        req = server.request(mockReader([HDR('Host: google.com'),
                                         HDRE]))
        run_generator(req.read_headers())
        self.assertEqual(req.headers, {b'Host': b'google.com'})

    def testHeadersSpaces(self):
        req = server.request(mockReader([HDR('Host:    \t    google.com   \t     '),
                                         HDRE]))
        run_generator(req.read_headers())
        self.assertEqual(req.headers, {b'Host': b'google.com'})

    def testHeadersEmptyValue(self):
        req = server.request(mockReader([HDR('Host:'),
                                         HDRE]))
        run_generator(req.read_headers())
        self.assertEqual(req.headers, {b'Host': b''})

    def testHeadersMultiple(self):
        req = server.request(mockReader([HDR('Host: google.com'),
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
        srv = server.webserver()
        for u in urls:
            srv.add_route(u[0], u[1])
        # Search them all
        for u in urls:
            # Create mock request object with "pre-parsed" url path
            rq = server.request(mockReader([]))
            rq.path = u[0].encode()
            f, args = srv._find_url_handler(rq)
            self.assertEqual(u[1], f)
        # Some simple negative cases
        for j in junk:
            rq = server.request(mockReader([]))
            rq.path = j.encode()
            f, args = srv._find_url_handler(rq)
            self.assertIsNone(f)
            self.assertIsNone(args)

    def testUrlFinderParameterized(self):
        srv = server.webserver()
        # Add few routes
        srv.add_route('/', 0)
        srv.add_route('/<user_name>', 1)
        srv.add_route('/a/<id>', 2)
        # Check first url (non param)
        rq = server.request(mockReader([]))
        rq.path = b'/'
        f, args = srv._find_url_handler(rq)
        self.assertEqual(f, 0)
        # Check second url
        rq.path = b'/user1'
        f, args = srv._find_url_handler(rq)
        self.assertEqual(f, 1)
        self.assertEqual(args, {'param_name': 'user_name'})
        self.assertEqual(rq._param, 'user1')
        # Check third url
        rq.path = b'/a/123456'
        f, args = srv._find_url_handler(rq)
        self.assertEqual(f, 2)
        self.assertEqual(args, {'param_name': 'id'})
        self.assertEqual(rq._param, '123456')
        # When param is empty and there is no non param endpoint
        rq.path = b'/a/'
        f, args = srv._find_url_handler(rq)
        self.assertEqual(f, 2)
        self.assertEqual(rq._param, '')

    def testUrlFinderNegative(self):
        srv = server.webserver()
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
        # Wrong parameterized URL (missed '<')
        with self.assertRaises(ValueError):
            srv.add_route('/id>', 1)


class ServerFull(unittest.TestCase):

    def testSimpleGETRequest(self):
        rdr = mockReader(['GET /junk/?abc=abc&cde=cde HTTP/1.1\r\n',
                          HDR('Host: blah.com'),
                          HDR('Content-Type: junk-junk'),
                          HDRE])
        wrt = mockWriter()
        srv = server.webserver()
        run_generator(srv._handler(rdr, wrt))
        # TODO: test incomplete. Mapping / Assertion must be added
        # Connection must be closed
        self.assertTrue(wrt.closed)

    # def testStartHTML(self):
    #     rdr = mockReader(['GET / HTTP/1.1\r\n',
    #                       HDR('Host: blah.com'),
    #                       HDRE])
    #     wrt = mockWriter()
    #     srv = server.webserver()
    #     run_generator(srv._handler(rdr, wrt))
    #     # TODO: test incomplete. Mapping / Assertion must be added
    #     # Connection must be closed
    #     self.assertTrue(wrt.closed)

    def testMalformedRequest(self):
        """Verify that malformed request generates proper response (http err)"""
        rdr = mockReader(['GET /\r\n',
                          HDR('Host: blah.com'),
                          HDRE])
        wrt = mockWriter()
        srv = server.webserver()
        run_generator(srv._handler(rdr, wrt))
        exp = ['HTTP/1.0 400 Bad Request\r\n',
               'Content-Type: text/plain\r\n\r\n',
               'HTTP 400 Bad Request\r\n']
        self.assertEqual(wrt.history, exp)
        # Connection must be closed
        self.assertTrue(wrt.closed)


if __name__ == '__main__':
    unittest.main()
