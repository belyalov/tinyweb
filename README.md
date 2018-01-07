## TinyWeb [![Build Status](https://travis-ci.org/belyalov/tinyweb.svg?branch=master)](https://travis-ci.org/belyalov/tinyweb)
Simple and lightweight (thus - *tiny*) HTTP server for tiny devices like ESP8266 / ESP32 *(not tested yet)* running [micropython](https://github.com/micropython/micropython).
Having an simple HTTP server allows developers to create nice and modern UI for their IOT devices.
By itself - *tinyweb* is just simple TCP server which runs in top of **uasyncio** - async like library for micropython, therefore tinyweb is single threaded server.

### Features
* Fully asynchronous using [uasyncio](https://github.com/micropython/micropython-lib/tree/master/uasyncio) library for MicroPython.
* [Flask](http://flask.pocoo.org/) / [Flask-RESTful](https://flask-restful.readthedocs.io/en/latest/) like API.
* *Tiny* memory usage. So you can run it on devices like **ESP8266** which has about 64K of RAM. BTW, there is a huge room for optimizations - so your contributions are warmly welcomed.
* Support for static content serving from filesystem.
* Great unittest coverage. So you can be confident about quality :)

### Requirements
* [uasyncio](https://github.com/micropython/micropython-lib/tree/master/uasyncio) - micropython version of *async* library for big brother - python3.
* [uasyncio-core](https://github.com/micropython/micropython-lib/tree/master/uasyncio.core)

### Quickstart
Let's develop pretty simple static web application:
```python
import tinyweb
from tinyweb.static import send_file


# Create web server application
app = tinyweb.webserver()


# Index page (just to be sure - let's handle most popular index links)
@app.route('/')
@app.route('/index.html')
def index(req, resp):
    # Just send file - you don't need to worry about content type
    yield from send_file(req, resp, 'static/index.simple.html')


# Images
@app.route('/images/<fn>')
def images(req, resp, fn):
    # Send picture. Filename - in just a parameter
    yield from send_file(req, resp, 'static/images/{}'.format(fn))


if __name__ == '__main__':
    app.run()
```
Simple? Oh yeah!

P.S. more documentation coming soon!
