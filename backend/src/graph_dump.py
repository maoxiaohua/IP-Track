import json, urllib.request
from core.auth import create_access_token
token = create_access_token('claude-verify', 1, 'admin')
req = urllib.request.Request('http://127.0.0.1:8100/api/v1/topology/graph',
    headers={'Authorization': f'Bearer {token}'})
data = json.loads(urllib.request.urlopen(req, timeout=300).read().decode())
none_unk = [n for n in data['nodes'] if n['kind']=='unknown' and not n.get('device_class')]
print(len(none_unk))
for n in none_unk[:12]:
    print(json.dumps(n, ensure_ascii=False)[:260])
