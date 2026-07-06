"""
Step 1: Visualize dig targets below player feet.
DigDown needs to mine 2 columns × 3 rows below feet = 6 tiles total.
Orange tiles (255, 165, 0) are shown via /path_vis_tiles.
Runs until Ctrl+C.
"""
import http.client, json, time

PORT = 17878

def get(path):
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=2)
    c.request('GET', path)
    return json.loads(c.getresponse().read())

def post(path, body):
    data = json.dumps(body).encode()
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=2)
    c.request('POST', path, data, {'Content-Type': 'application/json'})
    return json.loads(c.getresponse().read())

while True:
    try:
        state = get('/state')
        p = state['player']
        px = p['pos']['x']
        py = p['pos']['y']
        pw = p.get('width', 20)
        ph = p.get('height', 42)
        pcx = int((px + pw / 2) / 16)
        feet_y = int((py + ph) / 16)

        # DigDown mines leftCol and rightCol, 3 rows deep
        left_col  = px // 16
        right_col = (px + pw - 1) // 16
        cols = list(range(left_col, right_col + 1))

        tiles = []
        for dy in range(3):
            wy = feet_y + dy
            for col in cols:
                tiles.append({'wx': col, 'wy': wy, 'r': 255, 'g': 165, 'b': 0})

        result = post('/path_vis_tiles', tiles)
        print(f"\rpcx={pcx} feetY={feet_y} left={left_col} right={right_col} tiles={result.get('tiles')}    ", end='', flush=True)
    except Exception as e:
        print(f"\r{e}    ", end='', flush=True)
    time.sleep(0.1)
