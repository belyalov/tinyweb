## TinyWeb [![Build Status](https://travis-ci.org/belyalov/tinyweb.svg?branch=master)](https://travis-ci.org/belyalov/tinyweb)
Simple and lightweight (thus - *tiny*) HTTP server for tiny devices like **ESP8266** / **ESP32** running [micropython](https://github.com/micropython/micropython).
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


# Create web server application
app = tinyweb.webserver()


# Index page (just to be sure - let's handle most popular index links)
@app.route('/')
@app.route('/index.html')
def index(req, resp):
    # Just send file - you don't need to worry about content type
    yield from resp.send_file('static/index.simple.html')


# Images
@app.route('/images/<fn>')
def images(req, resp, fn):
    # Send picture. Filename - in just a parameter
    yield from resp.send_file('static/images/{}'.format(fn))


if __name__ == '__main__':
    app.run()
```
Simple? Oh yeah!

Like it? Check our [examples](https://github.com/belyalov/tinyweb/tree/master/examples) then :)

### Limitation / Known issues
* HTTP protocol support - due to memory constrains only **HTTP/1.0** is supported. Support of HTTP/1.1 may be added when `esp8266` platform will be completely deprecated.
* [esp8266: socket accept() does not always accept](https://github.com/micropython/micropython/issues/2490) - sometimes whenever you're opening connection simultaneously some of them will never be accepted. Therefore it is strongly recommended to pack all your data (like `css`, `js`) into single html page.

### Reference
#### class `webserver`
Main tinyweb app class.

* `add_route(self, url, f, **kwargs)` - Map `url` into function `f`. Additional keyword arguments are supported:
    * `methods` - List of allowed methods. Defaults to `['GET', 'POST']`
    * `parse_headers` - Sometimes you don't need / care about HTTP headers. So you can save some CPU cycles / memory by turning headers parse off. Default - `True`
    * `max_body_size` - Max HTTP body size (e.g. POST form data). Be careful with large forms due to memory constrains (especially with esp8266 which has 64K RAM). Defaults to `1024`.
    * `allowed_access_control_headers` - Whenever you're using xmlHttpRequest (send JSON from browser) these headers are required to do access control. Defaults to `*`
    * `allowed_access_control_origins` - The same idea as for header above. Defaults to `*`.

* `@route` - simple and useful decorator (inspired by *Flask*). Instead of using add_route() directly - just decorate your function with `@route`, like this:
    ```python
    @app.route('/index.html')
    def index(req, resp):
        yield from resp.send_file('static/index.simple.html')
    ```
* `add_resource(self, cls, url)` - RestAPI: Map resource class `cls` to `url`.  Class `cls` is arbitrary class with with implementation of HTTP methods:
    ```python
    class CustomersList():
        def get(self, data):
            """Return list of all customers"""
            return {'1': {'name': 'Jack'}, '2': {'name': 'Bob'}}

        def post(self, data):
            """Add customer"""
            db[str(next_id)] = data
        return {'message': 'created'}, 201
    ```
    **Note**: only `GET`, `POST`, `PUT` and `DELETE` methods are supported. Check [restapi full example](https://github.com/belyalov/tinyweb/blob/master/examples/rest_api.py) as well.

* `run(self, host="127.0.0.1", port=8081, loop_forever=True, backlog=10)` - run web server. Since *tinyweb* is fully async server by default it is blocking call assuming that you've added other tasks before.
    * `host` - host to listen on
    * `port` - port to listen on
    * `loop_forever` - run `async.loop_forever()`. Set to `False` if you don't want `run` to be blocking call. Be sure to call `async.loop_forever()` by yourself.
    * `backlog` - size of pending connections queue (basically argument to `listen()` function)

#### class `request`
This class contains everything about *HTTP request*. Use it to get HTTP headers / query string / etc.
***Warning*** - to improve memory / CPU usage string in `request` class are *binary strings*. This means that you **must** use `b` prefix when accessing items, e.g.

    >>> print(req.method)
    b'GET'

So be sure to check twice your code which interacts with `request`.

* `method` - HTTP request method. **Binary** string.
* `path` - URL path.
* `query_string` - URL path.
* `headers` - Parsed HTTP headers `dict` of key / value pairs.
    ```python
    if b'Content-Type' in self.headers:
        print(self.headers[b'Content-Type'])
    ```

* `read_parse_form_data()` - By default (again, to save CPU/memory) *tinyweb* doesn't read form data. You have to call it manually unless you're using RESTApi. Returns `dict` of key / value pairs.

#### class `response`
Use this class to generate some HTTP response. Please be noticed that `response` class is using *regular strings*, not binary strings as for `request` class does.

* `code` - HTTP response code. By default set to `200` which means OK, no error.
* `headers` - HTTP response headers dictionary (key / value pairs).

* `add_header(self, key, value)` - Convenient way to add HTTP response header
    * `key` - Header name
    * `value` - Header value

* `add_access_control_headers(self)` - Add HTTP headers required for RESTAPI (JSON query)

* `redirect(self, location)` - Generate HTTP redirection (HTTP 302 Found) to `location`. This *function is generator*.
* `start_html(self)`- Start response with HTML content type. This *function is generator*. This function is basically sends response line and headers. Refer to [hello world example](https://github.com/belyalov/tinyweb/blob/master/examples/hello_world.py).

* `send(self, payload)` - Sends your string/bytes `payload` to client. Be sure to start your response with `start_html()` or manually. This *function is generator*.

* `send_file(self, filename)`: Send local file as HTTP response. File type will be detected automatically unless you explicitly change it. If file doesn't exists - HTTP Error `404` will be generated.
Additional keyword arguments
    * `content_type` - MIME filetype. By default - `None` which means autodetect.
    * `max_age` - Cache control. How long browser can keep this file on disk. Value is in `seconds`. By default - 30 days. To disable caching, set it to `0`.

* `error(self, code)` - Generate HTTP error response with error `code`. This *function is generator*.
