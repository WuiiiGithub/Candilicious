import os
print("ENTER '1' IF THE REPO SHOULD BE CLONED")
print("ENTER '2' IF THE REPO SHOULD BE PULLED")
inp = input()
if inp == '1':
    os.system('git clone https://github.com/WuiiiGithub/Candlicious.git')
    os.system('mv ./Candilicious/* ./')
    os.system('mv ./Candilicious/.git ./')
    os.system('rm -rf ./Candilicious')

elif inp == '2':
    os.system('git pull https://github.com/WuiiiGithub/Candlicious.git')

print('='*1000)