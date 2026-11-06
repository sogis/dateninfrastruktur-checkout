"""Materialize an immutable multi-repo candidate and run a fresh independent review."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from tooling.workspace.gitops import clone_exact, digest, fingerprint, git, json_bytes, source_set, write_atomic
from tooling.workspace.inventory import WorkspaceError, read_json, within
from .contracts import binding, check_run, command_for, load_task, require


def binary():
    paths = [os.getenv('DI_OPENCODE'), shutil.which('opencode'),
             '/Applications/OpenCode.app/Contents/Resources/opencode-cli']
    paths += sorted((Path.home()/'Library/Application Support/ai.opencode.desktop/cli').glob('*/opencode-cli'))
    for path in filter(None,paths):
        if os.access(path,os.X_OK):
            probe = subprocess.run([path,'--version'],capture_output=True,text=True)
            version = probe.stdout.strip()
            if probe.returncode==0 and re.fullmatch(r'(?:opencode v)?2\.\d+\.\d+',version):
                return str(path),version
    raise WorkspaceError('NICHT_PRUEFBAR: OpenCode 2.x fehlt')


def tool_call(argv, cwd, env):
    process = subprocess.run(argv,cwd=cwd,env=env,capture_output=True,text=True)
    require(process.returncode==0,f'OpenCode-Befehl fehlgeschlagen: {argv[1]}')
    return process.stdout


def json_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def metadata(export):
    return {(message['model']['providerID']+'/'+message['model']['id'],message.get('agent'))
            for message in export['messages'] if message.get('type')=='assistant'}


class DocumentationText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts=[]

    def handle_data(self, data):
        self.parts.append(data)


def model_provenance(reviewer):
    # The current provider uses a moving API alias. Require the provider's
    # official mapping, in addition to the separately verified runtime alias.
    url='https://api-docs.deepseek.com/quick_start/agent_integrations/'
    require(reviewer['revision_source']==url and reviewer['model'].startswith('deepseek/'),
            'NICHT_PRUEFBAR: keine unterstützte Primärquelle zur Modellrevision')
    try:
        with urlopen(url,timeout=15) as response:
            require(response.geturl()==url,'NICHT_PRUEFBAR: unerwartete Weiterleitung der Modellquelle')
            data=response.read(2_000_000)
    except URLError as error:
        raise WorkspaceError('NICHT_PRUEFBAR: DeepSeek-Modellquelle nicht erreichbar') from error
    doc=DocumentationText()
    doc.feed(data.decode('utf-8'))
    alias=reviewer['model'].split('/')[1]
    revision=reviewer['model_revision']
    pattern=rf"Use\s+{re.escape(alias)}\s+as the model name\.\s+It is now served by\s+{re.escape(revision)}\b"
    require(re.search(pattern,' '.join(''.join(doc.parts).split())),
            'NICHT_PRUEFBAR: offizielle API-Modellzuordnung weicht ab')
    return {'source':url,'response_sha256':hashlib.sha256(data).hexdigest(),'alias':alias,'revision':revision}


def project_paths(root, rows):
    return {key:root if row['path']=='.' else within(root,row['path']) for key,row in rows.items()}


def dependency_fingerprint(paths, check):
    parts={}
    for identifier, files in check['dependency_files'].items():
        for name in files:
            parts[identifier+'/'+name]=digest(within(paths[identifier],name))
    require(parts and check['environment_id'], 'Leere Check-Abhängigkeit')
    return hashlib.sha256(json_bytes({
        'argv':check['argv'],'exit':check['exit'],'files':parts,'environment_id':check['environment_id'],
    })).hexdigest()


def carry(run, output, handoff, check_id, previous, fingerprint_value):
    require(re.fullmatch(r'[a-f0-9-]{36}',previous['run_id']), 'Ungültige Reviewreferenz')
    source_run = within(run.parent,previous['run_id'])
    accepted = read_json(within(source_run,'ACCEPTED.json'))
    prior = read_json(within(source_run,'handoff.json'))
    report_path = within(source_run,'output/review.json')
    require(accepted['report_sha256']==digest(report_path)
            and accepted['handoff_sha256']==digest(source_run/'handoff.json')
            and prior['specification_sha256']==handoff['specification_sha256']
            and prior['checks'][check_id]['dependency_fingerprint']==fingerprint_value,
            'Übernommene Beobachtung hat andere Eingaben')
    report = read_json(report_path)
    result, = (row for row in report['checks'] if row['requirement_id']==check_id)
    require(result['execution']=='EXECUTED' and result['status']=='PASS', 'Nur tatsächlich ausgeführter Beleg übernehmbar')
    source = within(source_run/'output',result['evidence']['path'])
    require(digest(source)==result['evidence']['sha256'], 'Quellbeleg verändert')
    shutil.copyfile(source,output/f'{check_id}.log')
    return {'reference':{'run_id':previous['run_id'],'session_id':accepted['session_id'],
        'report_sha256':accepted['report_sha256']},'source':result,'dependency_fingerprint':fingerprint_value}


def review(root, inventory, task, phase, *, exclude_untracked=False):
    require(task.is_absolute() and task.resolve()==task and not task.is_relative_to(root),
            'TASK_ROOT muss ein absoluter externer kanonischer Pfad sein')
    contract = load_task(task,phase)
    request = contract['request']
    reviewers = request['reviewer']
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',reviewers['model']) and
            reviewers['model_revision'] and reviewers['revision_source'].startswith('https://'),
            'Reviewermodell benötigt Providerkennung und öffentliche Modellrevision')
    provenance = model_provenance(reviewers)
    entries = inventory.select(ids=tuple(request['repositories']))
    require(request['repositories'] and len(entries)==len(request['repositories']),'Keine eindeutige Quellauswahl')
    capture = source_set(root,inventory,entries,allow_untracked=exclude_untracked)
    rows=capture['repositories']
    originals = project_paths(root,rows)
    original_state = {key:fingerprint(path) for key,path in originals.items()}
    run_id = str(uuid4())
    run = within(task,f'.work/reviews/{phase}/{run_id}')
    candidate, inputs, output = (run/name for name in ('workspace','inputs','output'))
    inputs.mkdir(parents=True)
    output.mkdir()
    candidates = project_paths(candidate,rows)
    for key in rows:
        clone_exact(originals[key],candidates[key],rows[key])
    candidate_state = {key:fingerprint(path) for key,path in candidates.items()}
    for name in contract['files']:
        dest=inputs/'contract'/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(within(task,name),dest)
    shutil.copyfile(within(task,f'.work/requests/{phase}.json'),inputs/'request.json')
    write_atomic(inputs/'source-set.json',capture)
    write_atomic(inputs/'model-provenance.json',provenance)
    for identifier,row in rows.items():
        base=request['bases'][identifier]
        require(re.fullmatch(r'[0-9a-f]{40}',base) and
                git(candidates[identifier],'merge-base','--is-ancestor',base,row['head'],optional=True) is not None,
                f'{identifier}: Basis ist kein Vorfahr')
        row['base']=base
    instructions = {}
    for key,path in candidates.items():
        rule = path/'AGENTS.md'
        if rule.is_file():
            instructions[f'{key}/AGENTS.md']=digest(rule)
    rules = request.get('additional_rules',[])
    for name in rules:
        source=within(task,name)
        dest=inputs/'rules'/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,dest)
        instructions['external/'+name]=digest(dest)
    checks={}
    for identifier,check in request['checks'].items():
        require(check['argv'] and all(isinstance(a,str) for a in check['argv']) and
                type(check['exit']) is int and 0<=check['exit']<=255, 'Ungültiger Prüfprozess')
        checks[identifier]=dict(check,shell_command=command_for(identifier,check['argv'],check['exit']),
            dependency_fingerprint=dependency_fingerprint(candidates,check))
    protected={p.relative_to(inputs).as_posix():digest(p) for p in inputs.rglob('*') if p.is_file()}
    agent_file = within(candidate,'.opencode/agents/independent-review.md')
    cli,version=binary()
    handoff=dict(schema_version=1,candidate_id=run_id,phase=phase,specification=contract['specification'],
        revision=contract['revision'],repositories=rows,created_at=datetime.now(timezone.utc).isoformat(),
        specification_sha256=contract['digest'],normative_files=contract['files'],
        request_sha256=contract['request_sha256'],source_set_sha256=digest(inputs/'source-set.json'),
        inventory_sha256=capture['inventory_sha256'],instructions=instructions,inputs=protected,
        reviewer=reviewers,cli_version=version,workspace=str(candidate),output='output',
        runner_sha256=digest(Path(__file__)),agent_sha256=digest(agent_file),
        required_checks=contract['required'],checks=checks,carried={},resources=request['resources'])
    for check_id,previous in request.get('carried',{}).items():
        handoff['carried'][check_id]=carry(run,output,handoff,check_id,previous,checks[check_id]['dependency_fingerprint'])
    write_atomic(run/'handoff.json',handoff)
    bound=binding(run/'handoff.json',handoff)
    write_atomic(run/'report-binding.json',bound)
    print(f'Kandidat {run}',flush=True)
    env=dict(os.environ,PWD=str(candidate),PYTHONDONTWRITEBYTECODE='1')
    env.pop('PYTHONOPTIMIZE',None)
    agents=json.loads(tool_call([cli,'debug','agents','--standalone'],candidate,env))
    require(any(a['id']=='independent-review' and a['mode']=='primary' for a in agents),
            'NICHT_PRUEFBAR: unabhängiger Projektagent fehlt')
    prompt=f"""You are the independent reviewer. Read ../handoff.json, ../report-binding.json, ../inputs/request.json,
../inputs/contract/{request['review_prompt']} and the other normative files. Evaluate the complete relevant delta.
Run each fresh check using the exact shell_command from handoff in the candidate workspace.
If a carried check exists, validate its original dependency identity and independently justify non-impact.
Design and run an additional counterprobe within output. No edits to tracked files, original workspace or settings.
Write review.md, review.json and evidence-manifest.json under ../output, using the normative report examples.
Use exact candidate ID and binding, actual observed results, file hashes and timing. Record counterexample.command as
the exact executed shell string, cwd, expected_exit and observed_exit, and marker as a distinctive full assertion line
present in both shell stdout and evidence. Include each check command_argv as the handoff argv, with real assertions
from the subprocess marker and started_at_utc/finished_at_utc. Run ID and candidate ID are {run_id}.
For negative outcomes report NACHARBEIT or NICHT_PRUEFBAR, never fabricate a pass.
Finish only after writing all three files."""
    argv=[cli,'run','--standalone','--agent','independent-review','--model',reviewers['model'],'--format','json']
    log=run/'events.jsonl'
    with log.open('w') as events,(run/'stderr.log').open('w') as stderr:
        result=subprocess.run(argv+[prompt],cwd=candidate,env=env,stdout=events,stderr=stderr)
        for _ in range(3):
            if result.returncode or all((output/f).is_file() for f in ('review.md','review.json','evidence-manifest.json')):
                break
            sessions={e['sessionID'] for e in json_lines(log) if e.get('sessionID')}
            if len(sessions)!=1:
                break
            result=subprocess.run(argv+['--session',sessions.pop(),
                'Finish this same review. Complete only the outstanding checks or reports and write all three outputs.'],
                cwd=candidate,env=env,stdout=events,stderr=stderr)
    trace=json_lines(log)
    sessions={e['sessionID'] for e in trace if e.get('sessionID')}
    require(len(sessions)==1,'NICHT_PRUEFBAR: fehlende/einander widersprechende Sessionereignisse')
    session=sessions.pop()
    exported=json.loads(tool_call([cli,'session','export','--standalone','--sanitize',session],candidate,env))
    write_atomic(run/'session.json',exported)
    actual=metadata(exported)
    unchanged=all(digest(within(inputs,name))==sha for name,sha in protected.items()) and \
        candidate_state=={key:fingerprint(path) for key,path in candidates.items()} and \
        digest(run/'handoff.json')==bound['handoff_sha256']
    prior_sessions=set()
    for p in run.parent.iterdir():
        if p!=run and (p/'runner.json').is_file():
            prior_sessions.add(read_json(p/'runner.json')['session_id'])
    runner=dict(session_id=session,cli_version=version,exit_code=result.returncode,
        model=reviewers['model'] if actual=={(reviewers['model'],'independent-review')} else 'UNVERIFIED',
        model_provenance_verified=bool(provenance),
        agent='independent-review' if actual=={(reviewers['model'],'independent-review')} else 'UNVERIFIED',
        errors=sum(e.get('type')=='error' for e in trace),fresh=session not in prior_sessions,
        candidate_unchanged=unchanged,
        original_unchanged=original_state=={key:fingerprint(path) for key,path in originals.items()})
    write_atomic(run/'runner.json',runner)
    report_path=within(output,'review.json')
    require(within(output,'review.md').stat().st_size>0,'Leerer Reviewbericht')
    check_run(handoff,bound,runner,read_json(report_path),read_json(within(output,'evidence-manifest.json')),output,trace)
    write_atomic(run/'ACCEPTED.json',dict(verdict='ABGENOMMEN',handoff_sha256=bound['handoff_sha256'],
        report_sha256=digest(report_path),runner_sha256=digest(run/'runner.json'),session_id=session))
    return run
