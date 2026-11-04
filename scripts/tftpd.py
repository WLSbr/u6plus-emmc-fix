import socket,struct,sys,os,threading
ROOT=os.path.abspath('fw')
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
s.bind(('0.0.0.0',69))
print('tftpd on 69',flush=True)
def serve(addr,fn,opts):
    c=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); c.settimeout(3)
    p=os.path.join(ROOT,os.path.basename(fn))
    data=open(p,'rb').read()
    bs=512
    if b'blksize' in opts:
        bs=int(opts[b'blksize'])
        oack=b'\x00\x06blksize\x00'+str(bs).encode()+b'\x00'
        if b'tsize' in opts: oack+=b'tsize\x00'+str(len(data)).encode()+b'\x00'
        c.sendto(oack,addr)
        try: c.recvfrom(64)
        except: return
    elif b'tsize' in opts:
        c.sendto(b'\x00\x06tsize\x00'+str(len(data)).encode()+b'\x00',addr)
        try: c.recvfrom(64)
        except: return
    n=0;blk=1
    while True:
        chunk=data[n:n+bs]
        pkt=struct.pack('>HH',3,blk&0xffff)+chunk
        for _ in range(8):
            c.sendto(pkt,addr)
            try:
                r,_=c.recvfrom(64)
                if struct.unpack('>HH',r[:4])==(4,blk&0xffff): break
            except socket.timeout: pass
        else: print('abort',blk,flush=True); return
        n+=bs;blk+=1
        if len(chunk)<bs: break
    print('sent',len(data),'bytes',flush=True)
while True:
    r,addr=s.recvfrom(1024)
    if struct.unpack('>H',r[:2])[0]==1:
        parts=r[2:].split(b'\x00')
        fn=parts[0].decode(); opts={parts[i].lower():parts[i+1] for i in range(2,len(parts)-1,2)}
        print('RRQ',fn,opts,flush=True)
        threading.Thread(target=serve,args=(addr,fn,opts),daemon=True).start()
