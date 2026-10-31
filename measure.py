.stat{padding:8px 14px;background:#141922;border-radius:6px}#message{color:#e0bf7c}
</style></head><body>
<h1>Light Measure</h1><div class="muted">AS7341 · 8-band spectrum · ESP32 over Wi-Fi</div>
<div class="panel"><div class="row">
<div class="stat" id="status">Waiting for readings…</div><div class="stat" id="samples">0 samples</div><div class="stat" id="meta">No device connected</div>
</div><canvas id="chart"></canvas><small>Raw AS7341 counts (not calibrated radiant power). Channels are broad and overlapping.</small></div>
<div class="panel"><div class="row">
<button onclick="capture()" id="capture">Capture current spectrum</button>
<button onclick="setBackground()">Set background / dark reference</button>
<button onclick="clearBackground()">Clear background</button>
<label><input type="checkbox" id="subtract" checked>Subtract background</label>
<a class="button" href="/api/export.csv">Export CSV</a>
</div><p id="message" class="muted">For a clean scan, measure background illumination first, then position the light source without moving the sensor.</p>
<div id="captured" class="muted">No capture yet.</div></div>
<script>
const W=[415,445,480,515,555,590,630,680], colors=['#8860cc','#5875db','#3baccb','#59bb9b','#8eb96c','#d9b74a','#e18b4d','#c25a5b'];
const canvas=document.getElementById('chart'), ctx=canvas.getContext('2d');
let latest=null, background=null, snapshot=null;
function draw(){
let width=canvas.clientWidth,height=canvas.clientHeight,dpr=window.devicePixelRatio||1;
canvas.width=Math.round(width*dpr); canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);
ctx.clearRect(0,0,width,height);
let vals=latest?latest.channels.map((v,i)=>Math.max(0,v-((background&&document.getElementById('subtract').checked)?background[i]:0))):Array(8).fill(0);
let max=Math.max(100, ...vals)*1.14, left=57,right=18,top=20,bottom=49,plotW=width-left-right,plotH=height-top-bottom;
ctx.strokeStyle='#303946';ctx.fillStyle='#b4bdcb';ctx.font='12px system-ui';
for(let i=0;i<=4;i++){let y=top+plotH*i/4, value=Math.round(max*(1-i/4));ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(width-right,y);ctx.stroke();ctx.fillText(String(value),5,y+4)}
let group=plotW/8,bar=Math.max(4,group*.62);
vals.forEach((v,i)=>{let h=v/max*plotH,x=left+i*group+(group-bar)/2,y=top+plotH-h;
ctx.fillStyle=colors[i];ctx.fillRect(x,y,bar,h);ctx.fillStyle='#e5e9f1';ctx.textAlign='center';ctx.fillText(String(Math.round(v)),x+bar/2,Math.max(13,y-5));ctx.fillStyle='#bac4d1';ctx.fillText(W[i]+' nm',x+bar/2,height-22)});ctx.textAlign='start';
}
function capture(){if(!latest)return; snapshot=[...latest.channels];document.getElementById('captured').textContent='Captured '+new Date().toLocaleTimeString()+': '+snapshot.map((v,i)=>W[i]+'nm='+v).join('  ·  ');}
function setBackground(){if(!latest)return;background=[...latest.channels];document.getElementById('message').textContent='Background saved from most recent reading; subtraction enabled.';draw()}
function clearBackground(){background=null;document.getElementById('message').textContent='Background cleared.';draw()}
document.getElementById('subtract').addEventListener('change',draw);window.addEventListener('resize',draw);
async function refresh(){try{let r=await fetch('/api/latest',{cache:'no-store'});if(!r.ok)throw Error(r.status);let d=await r.json();
if(d.latest){latest=d.latest;document.getElementById('status').textContent='Last reading '+new Date(latest.timestamp*1000).toLocaleTimeString();document.getElementById('meta').textContent=(latest.device||'ESP32')+' · '+(latest.gain||'?')+' gain';}
document.getElementById('samples').textContent=d.count+' samples';draw();}catch(e){document.getElementById('status').textContent='Server unavailable';}}
refresh();setInterval(refresh,400);
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def send(self, status, content, kind="application/json", filename=None):
        data = content.encode('utf-8') if isinstance(content,str) else content
        self.send_response(status)
        self.send_header('Content-Type',kind+'; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/': return self.send(200,HTML,'text/html')
        if path=='/api/latest':
            with lock: latest=history[-1] if history else None; count=len(history)
            return self.send(200,json.dumps({'latest':latest,'count':count}))
        if path=='/api/export.csv':
            buf=io.StringIO(); w=csv.writer(buf)
            w.writerow(['timestamp_utc','device','gain','atime','astep',*[f'{x}nm' for x in W],'clear','nir'])
            with lock: rows=list(history)
            for r in rows:
                w.writerow([datetime.fromtimestamp(r['timestamp']).isoformat()+'Z',r['device'],r['gain'],r['atime'],r['astep'],*r['channels'],r['clear'],r['nir']])
            return self.send(200,buf.getvalue(),'text/csv','light_measure.csv')
        return self.send(404,'{"error":"not found"}')

    def do_POST(self):
        if urlparse(self.path).path != '/api/reading':return self.send(404,'{"error":"not found"}')
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<=0 or length>4096: raise ValueError('invalid body size')
            d=json.loads(self.rfile.read(length))
            v=d['channels']
            if not isinstance(v,list) or len(v)!=8 or not all(type(x) is int and 0<=x<=65535 for x in v):
                raise ValueError('channels must contain eight integers 0..65535')
            r={'timestamp':time.time(),'device':str(d.get('device','esp32-c6'))[:64], 'channels':v,
               'clear':int(d.get('clear',0)),'nir':int(d.get('nir',0)),
               'gain':str(d.get('gain','1x'))[:16], 'atime':int(d.get('atime',29)),'astep':int(d.get('astep',599))}
            with lock:history.append(r)
            return self.send(200,'{"ok":true}')
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:
            return self.send(400,json.dumps({'error':str(e)}))

    def log_message(self, fmt, *args):
        if self.path != '/api/latest': super().log_message(fmt,*args)

if __name__=='__main__':
    p=argparse.ArgumentParser(description='AS7341 Wi-Fi spectrum viewer')
    p.add_argument('--host',default='0.0.0.0');p.add_argument('--port',type=int,default=8765)
    args=p.parse_args()
    print(f'Listening on http://{args.host}:{args.port} (open http://localhost:{args.port} on this Mac)')
    print('Use this only on a trusted local network; no authentication is configured.')
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
