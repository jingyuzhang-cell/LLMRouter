import sys
import urllib.request
from pathlib import Path
BLOCKS=Path(__file__).parent/'NETWORK_OR_CREDENTIAL_DENIALS.log'
def deny(*a,**kw):
    with BLOCKS.open('a') as f:f.write('blocked network or credential access\n')
    raise RuntimeError('ZERO_API_ACCEPTANCE_DENIED')
def audit(event,args):
    if event in ('socket.connect','socket.getaddrinfo'):deny()
    if event=='open' and isinstance(args[0],str) and (args[0].startswith('/root/.zcode/') or args[0].startswith('/root/.env')):deny()
sys.addaudithook(audit)
urllib.request.urlopen=deny
import pilot_common
pilot_common._api_key=deny
