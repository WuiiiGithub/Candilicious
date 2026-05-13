import subprocess

subprocess.call([
    'protonvpn',
    'connect'
])

def shut_vpn():
    subprocess.call([
        'protonvpn',
        'disconnect'
    ])