import socket, json

sock_path = '/work/@appcenter/rawarchiver/rawarchiver.sock'
out = open('/work/1000/pvtest.txt', 'w')

def req_post(path, body):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(120)
    s.connect(sock_path)
    payload = json.dumps(body).encode('utf-8')
    r = ("POST %s HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % (path, len(payload))).encode('utf-8') + payload
    s.sendall(r)
    data = b''
    while True:
        try:
            c = s.recv(4096)
            if not c:
                break
            data += c
        except socket.timeout:
            break
    s.close()
    return data.decode('utf-8', 'replace')

for src in ['/vol00/MassStorageClass/DCIM', '/vol1/1000/Photos']:
    r = req_post('/app/rawarchiver/api?action=preview', {'action': 'preview', 'source': src, 'output': '/vol1/1000/Photos'})
    out.write('===== source=%s =====\n%s\n\n' % (src, r[:800]))

out.close()
