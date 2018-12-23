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
@app.route('/index.html')
async def index(req, resp):
    # Just send file
    await resp.send_file('static/index.simple.html')


# Images
@app.route('/images/<fn>')
async def images(req, resp, fn):
    # Send picture. Filename - in parameter
    await resp.send_file('static/images/{}'.format(fn),
                         content_type='image/jpeg')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081)
    # To test your server just open page in browser:
    #   http://localhost:8081
    #   or
    #   http://localhost:8081/index.html
