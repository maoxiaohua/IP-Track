import json, urllib.request, collections
from core.auth import create_access_token

token = create_access_token('claude-verify', 1, 'admin')
req = urllib.request.Request(
    'http://127.0.0.1:8100/api/v1/topology/graph',
    headers={'Authorization': f'Bearer {token}'},
)
data = json.loads(urllib.request.urlopen(req, timeout=300).read().decode())
nodes = data.get('nodes', [])
links = data.get('links', [])
kinds = collections.Counter(n.get('kind') for n in nodes)
classes = collections.Counter(n.get('device_class') for n in nodes)
deg0 = collections.Counter(n.get('kind') for n in nodes if not n.get('degree'))
print('nodes', len(nodes), 'links', len(links))
print('kinds', dict(kinds))
print('classes', dict(classes))
print('degree0', dict(deg0))
net = [n for n in nodes if n.get('device_class') in ('switch', 'router', 'hub')]
non = [n for n in nodes if n.get('device_class') in ('host', 'phone')]
other = [n for n in nodes if n.get('device_class') not in ('switch', 'router', 'hub', 'host', 'phone')]
print('network', len(net), 'non-network', len(non), 'other', len(other))
for n in other[:10]:
    print('  other:', n.get('label'), n.get('device_class'), n.get('sys_desc'))
