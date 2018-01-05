#!/usr/bin/env micropython
"""
MIT license
(C) Konstantin Belyalov 2017-2018
"""
import tinyweb
from tinyweb.static import send_file


# Create web server application
app = tinyweb.webserver()


# Index page
@app.route('/')
@app.route('/index.html')
def index(request, response):
    # Just send file
    yield from send_file(response, 'static/index.html')


# Images
@app.route('/images/<fn>')
def images(request, response, fn):
    # Send picture. Filename - in parameter
    yield from send_file(response, 'static/images/{}'.format(fn))


if __name__ == '__main__':
    app.run()
    # To test your server just open page in browser:
    #   http://localhost:8081
    #   or
    #   http://localhost:8081/index.html
