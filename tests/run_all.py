import os,sys,subprocess,pathlib,yaml
ROOT=pathlib.Path(__file__).resolve().parents[1]
env={**os.environ,'EXA_API_KEY':'test','CEREBRAS_API_KEY':'test','TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHANNEL':'@ComicsNewsroom','PYTHONPATH':f"{ROOT/'tests'/'stubs'}:{ROOT}"}
checks=[
 ('py_compile',[sys.executable,'-m','py_compile',str(ROOT/'main.py')]),
 ('self_test',[sys.executable,str(ROOT/'main.py'),'--self-test']),
 ('fixture_test',[sys.executable,str(ROOT/'main.py'),'--fixture-test']),
 ('schema_contract',[sys.executable,str(ROOT/'tests/schema_contract.py')]),
 ('fault_injection',[sys.executable,str(ROOT/'tests/fault_injection.py')]),
 ('ai_pipeline_smoke',[sys.executable,str(ROOT/'tests/ai_pipeline_smoke.py')]),
 ('template_matrix',[sys.executable,str(ROOT/'tests/template_matrix.py')]),
 ('transport_smoke',[sys.executable,str(ROOT/'tests/transport_smoke.py')]),
 ('production_smoke',[sys.executable,str(ROOT/'tests/production_smoke.py')]),
]
results=[]
for name,cmd in checks:
    p=subprocess.run(cmd,env=env,cwd=ROOT,capture_output=True,text=True)
    output=(p.stdout+'\n'+p.stderr).strip()
    ok=p.returncode==0
    results.append((name,ok,output))
    print(f'[{"PASS" if ok else "FAIL"}] {name}')
    print(output[-1800:])
    if not ok:
        raise SystemExit(1)
wf=(ROOT/'.github/workflows/newbot.yml').read_text()
data=yaml.safe_load(wf); on=data['on'] if 'on' in data else data[True]
assert [x['cron'] for x in on['schedule']]==['0 0,3,6,9,12,15,18,21 * * *']
assert '@ComicsNewsroom' in wf and '--fixture-test' in wf
assert 'run: python main.py' in wf
print('[PASS] workflow_contract')
print('ALL OFFLINE TESTS: PASS')
