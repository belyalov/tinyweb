#!/usr/bin/env micropython
"""
MIT license
(C) Konstantin Belyalov 2017-2020
"""
import tinyweb
import uasyncio


# Create web server application
app = tinyweb.webserver(host='0.0.0.0', port=8081)


# Index page
@app.route('/')
async def index(request, response):
    # Start HTTP response with content-type text/html
    await response.start_html()
    # Send actual HTML page
    await response.send('<html><body><h1>Hello, world! (<a href="/table">table</a>)</h1></html>\n')


# HTTP redirection
@app.route('/redirect')
async def redirect(request, response):
    # Start HTTP response with content-type text/html
    await response.redirect('/')


# Another one, more complicated page
@app.route('/table')
async def table(request, response):
    # Start HTTP response with content-type text/html
    await response.start_html()
    await response.send('<html><body><h1>Simple table</h1>'
                        '<table border=1 width=400>'
                        '<tr><td>Name</td><td>Some Value</td></tr>')
    for i in range(10):
        await response.send('<tr><td>Name{}</td><td>Value{}</td></tr>'.format(i, i))
    await response.send('</table>'
                        '</html>')


async def main():
    await app.start()


if __name__ == '__main__':
    uasyncio.run(main())
    uasyncio.get_event_loop().run_forever()
    # To test your server:
    # - Terminal:
    #   $ curl http://IP_ADDR:8081
    #   or
    #   $ curl http://IP_ADDR:8081/table
    #
    # - Browser:
    #   http://IP_ADDR:8081
    #   http://IP_ADDR:8081/table
    #
    # - To test HTTP redirect:
    #   curl http://IP_ADDR:8081/redirect -v
