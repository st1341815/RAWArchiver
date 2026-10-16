import socket

sock_path = '/work/@appcenter/rawarchiver/rawarchiver.sock'
out = open('/work/1000/devtest.txt', 'w')

def req(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect(sock_path)
    r = "GET %s HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n" % path
    s.sendall(r.encode())
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

r = req('/app/rawarchiver/api?action=devices')
out.write(r)
out.close()
