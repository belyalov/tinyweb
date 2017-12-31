"""
Unittests for Tiny Web
MIT license
"""

import unittest
import tinyweb.server as server

# Helpers

# HTTP headers helpers
HDRE = '\r\n'


def HDR(str):
    return '{}\r\n'.format(str)


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

    def testMalformedRequest(self):
        rdr = mockReader(['GET /\r\n',
                          HDR('Host: blah.com'),
                          HDRE])
        wrt = mockWriter()
        srv = server.webserver()
        run_generator(srv._handler(rdr, wrt))
        # Request should generate HTTP 400 response
        self.assertEqual(wrt.history, ['HTTP/1.0 400 Bad Request\r\n\r\n'])
        # Connection must be closed
        self.assertTrue(wrt.closed)


if __name__ == '__main__':
    unittest.main()
