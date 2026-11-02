"""Enter a Groq Free-tier key into the running local demo's memory only."""
import argparse
import getpass
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args()
    print('Use a Groq organization on the Free plan. Check this in your Groq console.')
    print('This script does not verify the billing plan with Groq and does not upgrade it.')
    if input('Type FREE to confirm the organization is on the Free plan: ').strip()!='FREE':
        print('Not enabled.'); return
    key=getpass.getpass('Groq API key (hidden): ').strip()
    # Read-only credential check: no generation and no billing-plan inference.
    check=Request('https://api.groq.com/openai/v1/models',headers={
        'Authorization':'Bearer '+key,'User-Agent':'LIBRA-ADVICE/1.0'})
    try:
        with urlopen(check,timeout=15) as response:
            if response.status!=200:raise ValueError()
    except HTTPError as exc:
        print(f'Groq rejected the connection check (HTTP {exc.code}). Check the key and model access in the Groq console. No key was saved.');return
    except (URLError,ValueError,TimeoutError):
        print('Could not reach Groq to verify the connection. No key was saved.');return
    payload=json.dumps({'api_key':key,'free_tier_confirmed':True}).encode()
    request=Request(f'http://127.0.0.1:{args.port}/_local/configure-groq',data=payload,
        headers={'Content-Type':'application/json','X-Libra-Local-Setup':'hidden-prompt'},method='POST')
    try:
        with urlopen(request,timeout=5) as response:
            if not json.load(response).get('configured'):raise ValueError()
    except (URLError,ValueError):
        print('Could not enable Groq. Ensure the updated local demo is running on this port and the key is valid.');return
    print('GROQ ENABLED LOCALLY. The key is held in server memory only; no file was written.')

if __name__=='__main__':main()
