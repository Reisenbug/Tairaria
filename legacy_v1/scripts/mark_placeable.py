import urllib.request, json

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
req = urllib.request.Request("http://127.0.0.1:17878/mark_placeable", data=b'{}', method="POST")
with opener.open(req, timeout=3) as r:
    print(json.loads(r.read()))
