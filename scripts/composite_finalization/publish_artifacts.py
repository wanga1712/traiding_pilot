import csv,gzip,hashlib,json,shutil,sys
from pathlib import Path
root=Path('/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1')
audit=json.loads(sys.stdin.read())
assert audit['FINAL_OUTPUT_AUDIT']=='PASS'
out=root/'publication_20260921_v1';out.mkdir(exist_ok=False)
manifest={'artifact':'composite_publication_manifest_v1','format':'Concatenate decompressed gzip chunks in manifest order to reconstruct exact canonical bytes. Unchunked files are exact copies.','files':[]}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
for entry in audit['files']:
 p=Path(entry['path']); item=dict(entry);item['chunks']=[]
 assert sha(p)==entry['sha256']
 if p.stat().st_size>90*1024**2:
  with p.open('rb') as f:
   i=0
   while True:
    data=f.read(32*1024**2)
    if not data:break
    name=p.name+'.part-%04d.gz'%i
    with (out/name).open('wb') as dest:
     with gzip.GzipFile(filename='',mode='wb',fileobj=dest,mtime=0,compresslevel=6) as z:z.write(data)
    item['chunks'].append({'path':name,'bytes':(out/name).stat().st_size,'sha256':sha(out/name),'uncompressed_bytes':len(data),'uncompressed_sha256':hashlib.sha256(data).hexdigest()})
    i+=1
  check=hashlib.sha256()
  for chunk in item['chunks']:
   with gzip.open(out/chunk['path'],'rb') as z:
    for b in iter(lambda:z.read(1024*1024),b''):check.update(b)
  assert check.hexdigest()==entry['sha256']
 else:
  shutil.copyfile(p,out/p.name)
  item['publication_path']=p.name
 manifest['files'].append(item)
for name in ['composite_execution_checkpoint_v1.json','bounded_compose_run_status_v1.json',
 'composite_enumeration_authority_v1.json','runtime_repair_deployment_v1.json',
 'finalize_bounded_repaired_20260921.log','finalize_bounded_repaired_20260921.time',
 'data_provenance_preflight_v1.json','full_composite_execution_authority_v1.json']:
 shutil.copyfile(root/name,out/name)
(out/'composite_publication_manifest_v1.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'PUBLICATION_DIR':str(out),'PUBLICATION_REASSEMBLY_HASH_AUDIT':'PASS','files':len(list(out.iterdir())),'bytes':sum(p.stat().st_size for p in out.iterdir())},indent=2))
