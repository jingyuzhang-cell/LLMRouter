import sys
import urllib.request

def deny(*args, **kwargs):
    raise RuntimeError("ZERO_API_TEST_NETWORK_DENIED")
urllib.request.urlopen=deny
sys.addaudithook(lambda event,args: deny() if event in ('socket.connect','socket.getaddrinfo') else None)
import pilot_common
pilot_common._api_key=deny
