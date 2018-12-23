#!/usr/bin/env micropython

import machine
import network
import tinyweb
import gc


# PINs available for use
pins = {4: 'D2',
        5: 'D1',
        12: 'D6',
        13: 'D7',
        14: 'D5',
        15: 'D8',
        16: 'D0'}


# Create web server
app = tinyweb.server.webserver()


# Index page
@app.route('/')
@app.route('/index.html')
async def index(req, resp):
    await resp.send_file('static/index.html')


# JS files.
# Since ESP8266 is low memory platform - it totally make sense to
# pre-gzip all large files (>1k) and then send gzipped version
@app.route('/js/<fn>')
async def files_js(req, resp, fn):
    await resp.send_file('static/js/{}.gz'.format(fn),
                         content_type='application/javascript',
                         content_encoding='gzip')


# The same for css files - e.g.
# Raw version of bootstrap.min.css is about 146k, compare to gzipped version - 20k
@app.route('/css/<fn>')
async def files_css(req, resp, fn):
    await resp.send_file('static/css/{}.gz'.format(fn),
                         content_type='text/css',
                         content_encoding='gzip')


# Images
@app.route('/images/<fn>')
async def files_images(req, resp, fn):
    await resp.send_file('static/images/{}'.format(fn),
                         content_type='image/jpeg')


# RESTAPI: System status
class Status():

    def get(self, data):
        mem = {'mem_alloc': gc.mem_alloc(),
               'mem_free': gc.mem_free(),
               'mem_total': gc.mem_alloc() + gc.mem_free()}
        sta_if = network.WLAN(network.STA_IF)
        ifconfig = sta_if.ifconfig()
        net = {'ip': ifconfig[0],
               'netmask': ifconfig[1],
               'gateway': ifconfig[2],
               'dns': ifconfig[3]
               }
        return {'memory': mem, 'network': net}


# RESTAPI: GPIO status
class GPIOList():

    def get(self, data):
        res = []
        for p, d in pins.items():
            val = machine.Pin(p).value()
            res.append({'gpio': p, 'nodemcu': d, 'value': val})
        return {'pins': res}


# RESTAPI: GPIO controller: turn PINs on/off
class GPIO():

    def put(self, data, pin):
        # Check input parameters
        if 'value' not in data:
            return {'message': '"value" is requred'}, 400
        # Check pin
        pin = int(pin)
        if pin not in pins:
            return {'message': 'no such pin'}, 404
        # Change state
        val = int(data['value'])
        machine.Pin(pin).value(val)
        return {'message': 'changed', 'value': val}


def run():
    # Set all pins to OUT mode
    for p, d in pins.items():
        machine.Pin(p, machine.Pin.OUT)

    app.add_resource(Status, '/api/status')
    app.add_resource(GPIOList, '/api/gpio')
    app.add_resource(GPIO, '/api/gpio/<pin>')
    app.run(host='0.0.0.0', port=8081)


if __name__ == '__main__':
    run()
