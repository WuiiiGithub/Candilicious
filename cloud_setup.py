import os
while True:
    inp = input()
    print("ENTER 'clone' IF THE REPO SHOULD BE CLONED")
    print("ENTER 'fetch' IF THE REPO SHOULD BE FETCHED")

    if inp == 'clone':
        os.system('git clone https://github.com/WuiiiGithub/Candlicious.git')
        os.system('mv ./Candilicious/* ./')
        os.system('mv ./Candilicious/.git ./')
        os.system('rm -rf ./Candilicious')

    elif inp == 'fetch':
        os.system('git remote add origin https://github.com/WuiiiGithub/Candlicious.git')
        os.system('git fetch origin v1.x')

    elif inp == 'start':
        os.system("/home/container/.venv/bin/python3 main.py")
        break

    elif inp == 'install': 
        os.system("/home/container/.venv/bin/pip requirements.txt")

    elif inp == 'venv':
        os.system('python3 -m venv .venv')

    else:
        os.system(inp)

print('='*1000)