"""
Tiny Web - pretty simple and powerful web server for tiny platforms like ESP8266 / ESP32
MIT license
(C) Konstantin Belyalov 2017-2018
"""


def get_file_mime_type(fname):
    mime_types = {'html': 'text/html',
                  'css': 'text/css',
                  'js': 'application/javascript',
                  'png': 'image/png',
                  'jpg': 'image/jpeg',
                  'jpeg': 'image/jpeg',
                  'gif': 'image/gif'}
    idx = fname.rfind('.')
    if idx == -1:
        return 'text/plain'
    ext = fname[idx+1:]
    if ext not in mime_types:
        return 'text/plain'
    else:
        return mime_types[ext]
