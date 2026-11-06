"""Review contract parsing and evaluation. Phase identities belong to the external task."""
import hashlib
from pathlib import Path
import re
from shlex import join

from tooling.workspace.gitops import digest, json_bytes
from tooling.workspace.inventory import WorkspaceError, read_json, within

PHASE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*')
HASH = re.compile(r'[a-f0-9]{64}')


def require(condition, message):
    if not condition:
        raise WorkspaceError(message)


def load_task(root, phase):
    require(PHASE.fullmatch(phase), 'Ungültige Phase')
    manifest = read_json(within(root,'contracts/normative-files.json'))
    require(manifest['schema_version']==1,'Unbekannter Vertragsmanifesttyp')
    names = manifest['files']
    require(len(names)==len(set(names)) and
            {'contracts/normative-files.json','contracts/phase-checks.json'}<=set(names),
            'Unvollständige oder doppelte Vertragsliste')
    require(all(not name.startswith('.work/') for name in names),'Mutable Dateien im normativen Vertrag')
    files = {name:digest(within(root,name)) for name in sorted(names)}
    plan = read_json(within(root,'contracts/phase-checks.json'))
    require(plan['schema_version']==1 and all(plan[k]==manifest[k] for k in ('specification','revision')),
            'Versionskonflikt im Auftrag')
    request_path = within(root,f'.work/requests/{phase}.json')
    request = read_json(request_path)
    required = plan['phases'][phase]
    require(required and len(required)==len(set(required)) and
            all(PHASE.fullmatch(i) for i in required),'Ungültige Vertragscheckliste')
    require(request['schema_version']==1 and request['phase']==phase and
            all(request[k]==manifest[k] for k in ('specification','revision')),
            'Fremder oder veralteter Request')
    require(set(request['checks'])==set(required),'Request deckt Pflichtchecks nicht exakt ab')
    require(request['review_prompt'] in files,'Reviewerprompt fehlt im normativen Vertrag')
    return {
        'specification':manifest['specification'],'revision':manifest['revision'],
        'phase':phase,'required':required,'files':files,
        'digest':hashlib.sha256(json_bytes(files)).hexdigest(),
        'request_sha256':digest(request_path),'request':request,
    }


def evidence(output, entry):
    file = within(output, entry['path'])
    require(file.is_file() and file.stat().st_size == entry['bytes'] > 0 and
            digest(file)==entry['sha256'],f"Fehlender oder geänderter Beleg {entry['path']}")
    return file


def shell_result(events, command, cwd, default_cwd):
    matches = []
    for event in events:
        part = event.get('part',{})
        state = part.get('state',{})
        if event.get('type')!='tool_use' or part.get('tool')!='shell' or state.get('status')!='completed':
            continue
        args = state.get('input',{})
        if args.get('command')==command and args.get('workdir',default_cwd)==cwd:
            matches.append(state)
    require(matches, 'Kein passendes abgeschlossenes Shellereignis')
    return matches[-1]


def binding(handoff_path, handoff):
    return {key:handoff[key] for key in ('source_set_sha256','specification_sha256','request_sha256','repositories')} | {
        'handoff_sha256':digest(handoff_path)}


def check_run(handoff, expected, runner, report, manifest, output, events):
    def matching(fields):
        return all(report[k]==handoff[k] for k in fields)
    require(report['schema_version']==1 and not report.get('example_only') and
            matching(('candidate_id','specification','revision','phase')) and report['binding']==expected,
            'Bericht gehört zu anderem Kandidaten')
    require(runner['exit_code']==0 and runner['errors']==0 and runner['model']==handoff['reviewer']['model']
            and runner['model_provenance_verified'] and runner['agent']=='independent-review'
            and runner['session_id'] and runner['fresh'] and runner['candidate_unchanged'] and runner['original_unchanged'],
            'CLI-, Modell-, Session- oder Integritätsnachweis fehlt')
    require(report['reviewer']['runner_run_id']==manifest['run_id']==manifest['candidate_id']==handoff['candidate_id']
            and manifest['schema_version']==1 and not manifest.get('example_only'),'Fremdes Belegmanifest')
    require(all(report['integrity'][key] is True for key in ('product_unchanged','original_workspace_unchanged')),
            'Reviewer konnte Integrität nicht bestätigen')
    reports = report['checks']
    required = handoff['required_checks']
    require(sorted(x['requirement_id'] for x in reports)==sorted(required),'Fehlende, fremde oder doppelte Checks')
    recorded = {}
    workspace = handoff['workspace']
    for result in reports:
        check_id = result['requirement_id']
        contract = handoff['checks'][check_id]
        require(result['status']=='PASS' and result['required_assertions_skipped']==0
                and type(result['assertions_executed']) is int and result['assertions_executed']>0
                and result['started_at_utc'] and result['finished_at_utc'] and result['observation'],
                f'{check_id}: fehlender positiver Prüfbeleg')
        log = evidence(output,result['evidence'])
        require(log not in recorded,f'{check_id}: Belegpfad wiederverwendet')
        recorded[log] = result['evidence']
        if result['execution']=='CARRIED':
            carried = handoff['carried'].get(check_id)
            require(carried and result['carried_from']==carried['reference'] and
                    carried['source']['status']=='PASS' and carried['source']['execution']=='EXECUTED' and
                    carried['dependency_fingerprint']==contract['dependency_fingerprint'] and
                    result['evidence']['sha256']==carried['source']['evidence']['sha256']
                    and result['observation'] and result.get('nonimpact_reason'),
                    f'{check_id}: Belegübernahme ungebunden')
            for key in ('command_argv','cwd','expected_exit','observed_exit','assertions_executed','required_assertions_skipped'):
                require(result[key]==carried['source'][key],f'{check_id}: ursprünglichen Beleg umetikettiert')
            continue
        require(result['execution']=='EXECUTED' and check_id not in handoff['carried']
                and result['command_argv']==contract['argv'] and result['cwd']==workspace
                and result['expected_exit']==result['observed_exit']==contract['exit'],f'{check_id}: Befehlsbindung fehlt')
        command = contract['shell_command']
        event = shell_result(events, command, workspace, workspace)
        marker = f"ASSERTIONS={result['assertions_executed']} SKIP=0"
        require(event['metadata']['metadata']['exit']==0 and marker in event.get('output','').splitlines()
                and marker in log.read_text().splitlines(),f'{check_id}: echte Testassertions fehlen')
    counter = report['counterexample']
    require(counter['executed'] is True and counter['hypothesis'] and counter['expected'] and counter['observed'],
            'Eigenständige Gegenprobe fehlt')
    counter_file = evidence(output,counter['evidence'])
    require(counter_file not in recorded, 'Gegenprobe muss separaten Beleg haben')
    event = shell_result(events, counter['command'], counter['cwd'], workspace)
    require(event['metadata']['metadata']['exit']==counter['observed_exit']==counter['expected_exit']
            and counter['command'] not in {c['shell_command'] for c in handoff['checks'].values()}
            and counter['marker'] in event['output'].splitlines()
            and counter['marker'] in counter_file.read_text().splitlines(),'Gegenprobe fehlt als ausgeführter Test')
    recorded[counter_file] = counter['evidence']
    require(len(manifest['files'])==len(recorded) and
            {e['path']:e for e in manifest['files']}=={e['path']:e for e in recorded.values()},
            'Abweichendes Belegmanifest')
    require(report['verdict']=='ABGENOMMEN' and not report['not_executed'] and
            all(report['code_review'][key] is True for key in ('code_correct','goal_reached','scope_respected'))
            and not any(f['severity'].upper() in {'BLOCKER','MAJOR'} for f in report['findings']),
            'Review hat kein gültiges ABGENOMMEN')


def command_for(check_id, argv, expected):
    return (
        f"{join(argv)} > ../output/{check_id}.log 2>&1; actual=$?; "
        f"cat ../output/{check_id}.log; test \"$actual\" -eq {expected}"
    )
