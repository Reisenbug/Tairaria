import http.client, json, time

while True:
    try:
        c = http.client.HTTPConnection('127.0.0.1', 17878, timeout=1)
        c.request('GET', '/cursor')
        r = json.loads(c.getresponse().read())
        print(f"\rmx={r['mx']:+.3f}f, my={r['my']:+.3f}f  tile=({r['tile_x']},{r['tile_y']})    ", end='', flush=True)
    except Exception as e:
        print(f"\r{e}    ", end='', flush=True)
    time.sleep(0.05)
