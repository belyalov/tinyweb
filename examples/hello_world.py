#!/usr/bin/env micropython
"""
MIT license
(C) Konstantin Belyalov 2017-2018
"""
import tinyweb


# Create web server application
app = tinyweb.webserver()


# Index page
@app.route('/')
def index(request, response):
    # Start HTTP response with content-type text/html
    yield from response.start_html()
    # Send actual HTML page
    yield from response.send('<html><body><h1>Hello, world!</h1></html>\n')


# HTTP redirection
@app.route('/redirect')
def redirect(request, response):
    # Start HTTP response with content-type text/html
    yield from response.redirect('/')


# Another one, more complicated page
@app.route('/table')
def table(request, response):
    # Start HTTP response with content-type text/html
    yield from response.start_html()
    yield from response.send('<html><body><h1>Simple table</h1>'
                             '<table border=1 width=400>'
                             '<tr><td>Name</td><td>Some Value</td></tr>')
    for i in range(10):
        yield from response.send('<tr><td>Name{}</td><td>Value{}</td></tr>'.format(i, i))
    yield from response.send('</table>'
                             '</html>')


if __name__ == '__main__':
    app.run()
    # To test your server:
    # - Terminal:
    #   $ curl http://localhost:8081
    #   or
    #   $ curl http://localhost:8081/table
    # - Browser:
    #   http://localhost:8081
    #   http://localhost:8081/table
    #
    # - To test HTTP redirection:
    #   curl http://localhost:8081/redirect -v
