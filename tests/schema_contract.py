import os,sys,pathlib,re
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests'/'stubs'))
os.environ.update({'EXA_API_KEY':'test','CEREBRAS_API_KEY':'test','TELEGRAM_BOT_TOKEN':'test'})
import main

unsupported={'minItems','maxItems','pattern','format','oneOf','allOf','not','if','then','else','dependentRequired','dependentSchemas','patternProperties','unevaluatedProperties'}

schemas=[]
for name,value in vars(main).items():
    if name.endswith('_SCHEMA') and isinstance(value,dict): schemas.append((name,value))

def walk(node,path='root'):
    if isinstance(node,dict):
        bad=unsupported.intersection(node)
        assert not bad, (path,bad)
        if node.get('type')=='object':
            assert node.get('additionalProperties') is False, path
            props=node.get('properties',{})
            req=set(node.get('required',[]))
            assert req.issubset(set(props)), (path,'required missing')
            for k,v in props.items(): walk(v,f'{path}.{k}')
        if node.get('type')=='array':
            assert 'items' in node, path
            walk(node['items'],f'{path}[]')
        if '$defs' in node:
            for k,v in node['$defs'].items(): walk(v,f'{path}.$defs.{k}')
        if 'anyOf' in node:
            for i,v in enumerate(node['anyOf']): walk(v,f'{path}.anyOf[{i}]')

for name,schema in schemas: walk(schema,name)
# Strict schemas used by model must all be object roots.
assert len(schemas) >= 5
assert main.RANK_SCHEMA['properties']['ranked']['items']['properties']['sector']['enum']==main.SECTORS
assert main.STORY_SCHEMA['properties']['sector']['enum']==main.SECTORS
assert 'Marvel' not in main.SECTORS and 'DC' not in main.SECTORS
print('SCHEMA-CONTRACT TEST: PASS | schemas=%d | strict-compatible keyword audit passed' % len(schemas))
