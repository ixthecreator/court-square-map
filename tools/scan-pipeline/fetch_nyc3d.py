"""Fetch one delivery area of the NYC 3D Building Model (OTI, 2014 survey) without downloading the 257 MB zip.

The zip is read over HTTP range requests: only its directory and the members of the requested delivery area are
transferred (about 12 MB for DA10, which covers Long Island City).

Usage: python3 tools/scan-pipeline/fetch_nyc3d.py data/nyc3d [DA10]
"""
import io, os, subprocess, sys, zipfile

URL = 'https://s-media.nyc.gov/agencies/oti/DA_WISE_Multipatch.zip'


class HttpRange(io.RawIOBase):
    def __init__(self, url):
        self.url, self.pos, self.fetched = url, 0, 0
        head = subprocess.run(['curl', '-sIL', '-m', '60', url], capture_output=True, text=True).stdout
        self.size = int([l.split(':', 1)[1] for l in head.splitlines() if l.lower().startswith('content-length')][-1])

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n=-1):
        n = self.size - self.pos if n is None or n < 0 else min(n, self.size - self.pos)
        if n <= 0:
            return b''
        data = subprocess.run(['curl', '-s', '-m', '600', '-r', f'{self.pos}-{self.pos + n - 1}', self.url], capture_output=True).stdout
        self.pos += len(data); self.fetched += len(data)
        return data

    def readinto(self, b):
        d = self.read(len(b)); b[:len(d)] = d
        return len(d)


out = sys.argv[1]
area = sys.argv[2] if len(sys.argv) > 2 else 'DA10'
src = HttpRange(URL)
z = zipfile.ZipFile(io.BufferedReader(src, buffer_size=1 << 20))
want = [n for n in z.namelist() if (n.startswith(f'DA_WISE_Multipatch/{area}_') or n.startswith('DeliveryArea')) and not n.endswith('/')]
for n in want:
    dest = os.path.join(out, n)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with z.open(n) as s, open(dest, 'wb') as d:
        d.write(s.read())
print(f'{len(want)} files from {area}; {src.fetched / 1e6:.1f} MB transferred')
