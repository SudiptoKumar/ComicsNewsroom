import os, sys, subprocess, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
stubs=ROOT/'tests'/'stubs'
env=os.environ.copy()
env.update({"EXA_API_KEY":"test","CEREBRAS_API_KEY":"test","TELEGRAM_BOT_TOKEN":"test","CEREBRAS_MODEL":"gpt-oss-120b"})
code="import sys; sys.path.insert(0, r'%s')" % stubs
for args in [["--self-test"],["--fixture-test"]]:
    proc=subprocess.run([sys.executable,str(ROOT/"main.py"),*args],env={**env,"PYTHONPATH":str(stubs)},capture_output=True,text=True,cwd=ROOT)
    print("COMMAND",args)
    print(proc.stdout[-4000:])
    print(proc.stderr[-4000:])
    if proc.returncode!=0:
        raise SystemExit(proc.returncode)
print("OFFLINE EXECUTABLE PATH TEST: PASS")
