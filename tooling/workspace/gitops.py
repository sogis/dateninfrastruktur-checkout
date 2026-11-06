"""Git operations preserve existing worktrees and verify repository ownership."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from .inventory import WorkspaceError, within

ALLOW_FILES = {'.gitignore', 'AGENTS.md', 'LICENSE', 'README.md', 'repositories.json', 'workspace'}
ALLOW_DIRS = {'tooling', 'tests', 'docs', '.github/workflows'}
ALLOW_AGENT = '.opencode/agents/independent-review.md'
OID = re.compile(r'[0-9a-f]{40}')


def git(repo, *args, optional=False):
    env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git','-C',str(repo),*args], env=env, capture_output=True)
    if result.returncode:
        if optional:
            return None
        raise WorkspaceError(f'{repo.name}: Git-Befehl {args[0]} fehlgeschlagen (Exit {result.returncode})')
    return os.fsdecode(result.stdout).rstrip('\n')


def own_toplevel(path):
    return path.is_dir() and Path(git(path, 'rev-parse', '--show-toplevel', optional=True) or '/') == path


def state(path):
    if not own_toplevel(path):
        raise WorkspaceError(f'{path.name}: eigener Git-Toplevel fehlt')
    return {
        'head': git(path, 'rev-parse', 'HEAD'),
        'tree': git(path, 'rev-parse', 'HEAD^{tree}'),
        'branch': git(path, 'symbolic-ref', '--quiet', '--short', 'HEAD', optional=True),
        'status': git(path, 'status', '--porcelain=v1', '-z', '-uall').split('\0')[:-1],
        'index': hashlib.sha256(os.fsencode(git(path, 'ls-files', '--stage', '-z'))).hexdigest(),
    }


def remote_matches(path, remote):
    fetch = git(path, 'remote', 'get-url', '--all', 'origin', optional=True)
    push = git(path, 'remote', 'get-url', '--push', '--all', 'origin', optional=True)
    return fetch == push == remote and (remote is not None or not git(path,'remote'))


def inspect(root, entry):
    path = within(root, entry.path)
    if not path.exists():
        return {'id':entry.id,'path':entry.path,'state':'LOCAL_REPO_PENDING' if entry.remote is None else 'MISSING'}
    details = state(path)
    return {'id':entry.id,'path':entry.path,'state':'PRESENT' if remote_matches(path,entry.remote) else 'REMOTE_MISMATCH',**details}


def clone_missing(root, entry):
    path = within(root, entry.path)
    if path.exists():
        if inspect(root,entry)['state'] != 'PRESENT':
            raise WorkspaceError(f'{entry.id}: vorhandener Pfad hat eine fremde Identität')
        return 'PRESENT'
    if entry.remote is None:
        raise WorkspaceError(f'{entry.id}: lokales Repository noch ausstehend')
    # The staging directory is owned by this invocation, even on clone failure.
    with tempfile.TemporaryDirectory(prefix='.workspace-clone-', dir=root) as temp:
        staging = Path(temp)/'repository'
        git(root,'clone','--no-hardlinks','--branch',entry.branch,'--',entry.remote,str(staging))
        if not own_toplevel(staging) or not remote_matches(staging,entry.remote):
            raise WorkspaceError(f'{entry.id}: Herkunft des Klons unklar')
        # Reserve the destination. Directory rename may replace only our empty reservation.
        path.mkdir()
        reserved = path.stat()
        try:
            staging.rename(path)
        except OSError:
            if path.exists() and not path.is_symlink() and os.path.samestat(reserved,path.stat()):
                path.rmdir()
            raise
    return 'CLONED'


def sync(root, entry):
    path = within(root,entry.path)
    current = inspect(root,entry)
    if current['state'] != 'PRESENT' or entry.remote is None:
        raise WorkspaceError(f'{entry.id}: Herkunft für Sync unbestätigt')
    branch = current['branch']
    upstream = git(path,'rev-parse','--symbolic-full-name','@{upstream}',optional=True)
    expected = f'refs/remotes/origin/{entry.branch}'
    if current['status'] or branch != entry.branch or upstream != expected:
        raise WorkspaceError(f'{entry.id}: Sync erfordert sauberen Defaultbranch mit erwartetem Upstream')
    git(path,'fetch','--no-tags','--no-prune','origin',f'+refs/heads/{entry.branch}:{expected}')
    if inspect(root,entry) != current or git(path,'rev-parse','--symbolic-full-name','@{upstream}',optional=True)!=expected:
        raise WorkspaceError(f'{entry.id}: Repository während Sync geändert')
    left,right = map(int,git(path,'rev-list','--left-right','--count',f'HEAD...{expected}').split())
    if left and right:
        raise WorkspaceError(f'{entry.id}: Historie divergiert')
    if left:
        return 'AHEAD'
    if right:
        target = git(path,'rev-parse',expected)
        git(path,'merge','--ff-only','--no-edit',target)
        return 'FAST_FORWARD'
    return 'CURRENT'


def root_allowed(path):
    parts=Path(path).parts
    if (any(part.startswith('.env') or part in {'__pycache__','.runtime','node_modules'} for part in parts)
            or path.lower().endswith(('.pem','.key','.p12','.pyc'))):
        return False
    return path in ALLOW_FILES or path == ALLOW_AGENT or any(path.startswith(folder+'/') for folder in ALLOW_DIRS)


def verify_root(root, inventory):
    if not own_toplevel(root) or not remote_matches(root,inventory.remote):
        raise WorkspaceError('Root muss einen eigenen Git-Toplevel und das erwartete Remote haben')
    entries = git(root,'ls-files','--stage','-z').split('\0')
    for item in filter(None,entries):
        metadata, filename = item.split('\t',1)
        mode, _, stage = metadata.split()
        if stage != '0' or mode not in {'100644','100755'} or not root_allowed(filename):
            raise WorkspaceError(f'Unerlaubter Root-Indexpfad oder Modus {filename}')
    for item in filter(None,git(root,'ls-tree','-r','-z','HEAD').split('\0')):
        metadata, filename = item.split('\t',1)
        mode, _, _ = metadata.split()
        if mode not in {'100644','100755'} or not root_allowed(filename):
            raise WorkspaceError(f'Unerlaubter Root-Treepfad oder Modus {filename}')
    if not within(root,ALLOW_AGENT).is_file():
        raise WorkspaceError('Unabhängige Agentenanweisung fehlt')
    for entry in inventory.repositories:
        path = within(root,entry.path)
        if path.exists() and not own_toplevel(path):
            raise WorkspaceError(f'{entry.id}: erwartetes Kindrepo hat keinen eigenen Toplevel')
        if path.exists() and not remote_matches(path,entry.remote):
            raise WorkspaceError(f'{entry.id}: abweichendes Remote')
    return True


def file_record(path):
    if path.is_symlink():
        return ('symlink',os.readlink(path))
    if not path.is_file():
        return ('absent',)
    return ('regular',stat.S_IMODE(path.stat().st_mode),digest(path))


def fingerprint(path):
    details=state(path)
    files=git(path,'ls-files','--cached','--others','--exclude-standard','-z').split('\0')
    return details, {name:file_record(path/name) for name in sorted(set(files)-{''})}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value):
    return (json.dumps(value,sort_keys=True,indent=2,ensure_ascii=True)+'\n').encode()


def write_atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as temp:
        temporary = Path(temp.name)
        temp.write(json_bytes(value))
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def source_set(root, inventory, entries, *, allow_untracked=False):
    verify_root(root, inventory)
    rows = {}
    for identifier, path in [('workspace',root),*((e.id,within(root,e.path)) for e in entries)]:
        actual = state(path)
        if any(not allow_untracked or not item.startswith('?? ') for item in actual['status']):
            raise WorkspaceError(f'{identifier}: unveröffentlichte Änderungen')
        rows[identifier] = {'path':'.' if identifier=='workspace' else path.name,
                           'head':actual['head'],'tree':actual['tree']}
    for identifier,row in rows.items():
        actual = state(root/row['path'])
        if any(actual[key]!=row[key] for key in ('head','tree')) or any(
                not allow_untracked or not item.startswith('?? ') for item in actual['status']):
            raise WorkspaceError(f'{identifier}: inkonsistente Quellenaufnahme')
    return {'schema_version':1,'inventory_sha256':digest(root/'repositories.json'),'repositories':rows}


def clone_exact(original, target, row):
    git(original,'clone','--no-hardlinks','--no-checkout','--',str(original),str(target))
    git(target,'checkout','--detach',row['head'])
    if not OID.fullmatch(row['head']) or (target/'.git/objects/info/alternates').exists():
        raise WorkspaceError(f'{target.name}: ungültige oder geteilte Git-Metadaten')
    actual=state(target)
    if actual['head']!=row['head'] or actual['tree']!=row['tree'] or actual['status']:
        raise WorkspaceError(f'{target.name}: Kandidat weicht vom Quellstand ab')
    origin=git(original,'remote','get-url','origin',optional=True)
    if origin is None:
        git(target,'remote','remove','origin')
    else:
        git(target,'remote','set-url','origin',origin)
