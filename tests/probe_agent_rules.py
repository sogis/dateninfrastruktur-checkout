"""Run real read-only instruction discovery in two nested Git projects."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile

from tooling.review.runner import binary
from tooling.workspace.gitops import git

SOURCE=Path(__file__).resolve().parents[1]
QUESTION=("This read-only test concerns only your current Git project and parent rules explicitly "
          "referenced by its AGENTS.md. Do not inspect descendants. First read source.txt, "
          "then report its exact value and applicable rule tokens. Do not modify files.")


def probe(executable, agent, path, location, root_token, child_token, source):
    if agent=='Codex':
        argv=[executable,'exec','--sandbox','read-only','--ephemeral','--json','-C',str(path),QUESTION]
    else:
        argv=[executable,'run','--standalone','--agent','independent-review',
              '--model','deepseek/deepseek-flash','--format','json',QUESTION]
    proc=subprocess.run(argv,cwd=path,env=dict(os.environ,PWD=str(path)),capture_output=True,
                        text=True,timeout=180)
    assert proc.returncode==0,f'{agent} {location} failed (exit {proc.returncode})'
    events=[json.loads(row) for row in proc.stdout.splitlines() if row.startswith('{')]
    if agent=='Codex':
        actions=[e['item'] for e in events if e['type']=='item.completed']
        read=[a['command'] for a in actions if a['type']=='command_execution' and a.get('exit_code')==0]
        messages=[a['text'] for a in actions if a['type']=='agent_message']
    else:
        actions=[e['part'] for e in events if e['type']=='tool_use' and e['part']['state']['status']=='completed']
        read=[json.dumps(a['state'].get('input',{})) for a in actions if a['tool'] in {'read','shell'}]
        messages=[e['part']['text'] for e in events if e['type']=='text']
    final='\n'.join(messages)
    assert any('source.txt' in command for command in read),f'{agent} {location}: source not read'
    assert root_token in final and source in final,f'{agent} {location}: root rule/source missing'
    if location=='child':
        assert child_token in final and any('AGENTS.md' in command for command in read),f'{agent} child: explicit parent rule missing'
    else:
        assert child_token not in final,f'{agent} root: unrelated child rule'
    print(f'{agent} {location}: source read and applicable tokens confirmed')


def main():
    codex=shutil.which('codex')
    assert codex,'Codex CLI unavailable'
    opencode,_=binary()
    with tempfile.TemporaryDirectory(prefix='workspace-rules-') as temp:
        root=Path(temp).resolve()
        child=root/'child'
        child.mkdir()
        root_token,child_token,root_source,child_source=(secrets.token_hex(8) for _ in range(4))
        for location,path,rule,source in (
            ('root',root,f'Root rule token is {root_token}. Read only current project files.\n',root_source),
            ('child',child,f'Child token is {child_token}. Read ../AGENTS.md explicitly.\n',child_source),
        ):
            git(path,'init','-b','main')
            (path/'AGENTS.md').write_text(rule)
            (path/'source.txt').write_text(source+'\n')
            agents=path/'.opencode/agents'
            agents.mkdir(parents=True)
            shutil.copyfile(SOURCE/'.opencode/agents/independent-review.md',agents/'independent-review.md')
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(probe,cli,agent,path,location,root_token,child_token,source)
                for cli,agent in [(codex,'Codex'),(opencode,'OpenCode')]
                for path,location,source in [(root,'root',root_source),(child,'child',child_source)]]
            for future in futures:
                future.result()
    print('ASSERTIONS=4 SKIP=0')


if __name__=='__main__':
    main()
