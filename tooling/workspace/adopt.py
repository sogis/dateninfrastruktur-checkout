"""Journalled transfer of a standalone Git checkout into a nonempty root."""
import hashlib
import os
from pathlib import Path
import shutil

from .gitops import digest, file_record, fingerprint, git, json_bytes, own_toplevel, root_allowed, write_atomic
from .inventory import WorkspaceError, read_json, within


def require(condition, message):
    if not condition:
        raise WorkspaceError(message)


def children(root, names):
    return {name: {
        'git':fingerprint(within(root,name)),
        'fetch':git(root/name,'remote','-v'),
    } for name in names}


def stage_files(staging):
    entries={}
    for path in git(staging,'ls-files','-z').split('\0'):
        if not path:
            continue
        require(root_allowed(path),f'Unerlaubter Rootpfad {path}')
        record=file_record(within(staging,path))
        require(record[0]=='regular',f'Nicht reguläre Stagingdatei {path}')
        entries[path]=list(record)
    return entries


def plan(root, staging, child_names, journal, expected_head, original_agents):
    require(root.is_dir() and root.resolve()==root and not (root/'.git').exists() and
            git(root,'rev-parse','--show-toplevel',optional=True) is None,
            'Ziel ist kein unverzeichneter Workspace-Root')
    require(journal.is_absolute() and not journal.is_relative_to(root) and journal.resolve()==journal and
            not journal.exists(),'Neues Journal ausserhalb des Root erforderlich')
    require(staging.resolve()==staging and own_toplevel(staging) and
            not staging.is_relative_to(root) and (staging/'.git').is_dir() and
            not (staging/'.git/objects/info/alternates').exists() and
            git(staging,'config','--get','core.worktree',optional=True) is None,
            'Staging benötigt eigenständige Gitmetadaten')
    require(git(staging,'rev-parse','HEAD')==expected_head and
            not git(staging,'status','--porcelain=v1','-uall'),'Staging-SHA oder Zustand weicht ab')
    files=stage_files(staging)
    require('AGENTS.md' in files and original_agents.is_file() and
            file_record(root/'AGENTS.md')[0]=='regular' and
            digest(root/'AGENTS.md')==digest(original_agents),'Ursprüngliche AGENTS.md hat sich geändert')
    top=set(Path(p).parts[0] for p in files)-{'AGENTS.md'}
    for name in top|{'.git'}:
        path=root/name
        require(not path.exists() and not path.is_symlink(),f'Root-Kollision {name}')
    baseline=children(root,child_names)
    backup=journal.parent/'AGENTS.backup.md'
    with backup.open('xb') as output:
        output.write((root/'AGENTS.md').read_bytes())
    state=dict(schema=1,root=str(root),stage=str(staging),stage_head=expected_head,
        old_agents=list(file_record(root/'AGENTS.md')),files=files,children_digest=hashlib.sha256(json_bytes(baseline)).hexdigest(),
        child_names=child_names,origin=git(staging,'remote','get-url','origin'),
        root_entries=sorted(p.name for p in root.iterdir()),created=[],state='PLANNED')
    write_atomic(journal,state)
    return state


def advance(journal, *, interrupt_after=None):
    data=read_json(journal)
    root,staging=Path(data['root']),Path(data['stage'])
    require(root.resolve()==root and staging.resolve()==staging,'Root-/Stagingpfad verändert')
    require(git(staging,'rev-parse','HEAD')==data['stage_head'] and stage_files(staging)==data['files'],
            'Stagingquellen verändert')
    digest_now=hashlib.sha256(json_bytes(children(root,data['child_names']))).hexdigest()
    require(digest_now==data['children_digest'],'Mindestens ein Kindrepo hat sich geändert')
    backup=journal.parent/'AGENTS.backup.md'
    require(digest(backup)==data['old_agents'][-1],'Regelsicherung beschädigt')
    if data['state']=='DONE':
        require(own_toplevel(root) and git(root,'rev-parse','HEAD')==data['stage_head'],'Root nach Übernahme verändert')
        return data
    require(data['state'] in {'PLANNED','COPYING','FILES_READY','GIT_READY'},'Unbekannter Journalzustand')
    for name,record in data['files'].items():
        target=within(root,name)
        if name in data['created']:
            require(list(file_record(target))==record,f'Übernommene Datei verändert {name}')
        elif name=='AGENTS.md':
            require(list(file_record(target))==data['old_agents'],'Ursprüngliche AGENTS.md verändert')
        else:
            require(not target.exists() and not target.is_symlink(),f'Neue Kollision {name}')
    unexpected=set(p.name for p in root.iterdir())-set(data['root_entries'])
    require(unexpected<={Path(p).parts[0] for p in data['created']}|({'.git'} if data['state']=='GIT_READY' else set()),
            'Unbekannter Rootzustand nach Planung')
    if data['state'] in {'PLANNED','COPYING'}:
        data['state']='COPYING'
        write_atomic(journal,data)
        for name,record in data['files'].items():
            if name in data['created']:
                continue
            target=within(root,name)
            target.parent.mkdir(parents=True,exist_ok=True)
            content=(staging/name).read_bytes()
            if name=='AGENTS.md':
                temp=journal.parent/'AGENTS.install'
                with temp.open('xb') as output:
                    output.write(content)
                temp.chmod(record[1])
                temp.replace(target)
            else:
                with target.open('xb') as output:
                    output.write(content)
                target.chmod(record[1])
            data['created'].append(name)
            write_atomic(journal,data)
            if interrupt_after=='file':
                raise InterruptedError('test interruption after recorded file')
        data['state']='FILES_READY'
        write_atomic(journal,data)
        if interrupt_after=='files':
            raise InterruptedError('test interruption before Git transfer')
    if data['state']=='FILES_READY':
        target=root/'.git'
        require(not target.exists() and not target.is_symlink(),'Kollision Gitmetadaten')
        metadata=journal.parent/'standalone.git'
        require(not metadata.exists(),'Nicht journalisierter Metadaten-Transfer')
        shutil.copytree(staging/'.git',metadata,symlinks=True)
        metadata.rename(target)
        data['state']='GIT_READY'
        write_atomic(journal,data)
        if interrupt_after=='git':
            raise InterruptedError('test interruption after recorded Git transfer')
    require(own_toplevel(root) and git(root,'rev-parse','HEAD')==data['stage_head'] and
            git(root,'remote','get-url','origin')==data['origin'] and
            not git(root,'status','--porcelain=v1','-uall'),'Root-Git ist nach der Übernahme nicht konsistent')
    require(hashlib.sha256(json_bytes(children(root,data['child_names']))).hexdigest()==data['children_digest'],
            'Kindrepo während der Übernahme verändert')
    data['state']='DONE'
    write_atomic(journal,data)
    return data


def rollback(journal):
    data=read_json(journal)
    root=Path(data['root'])
    require(root.resolve()==root and data['state'] in {'PLANNED','COPYING','FILES_READY','GIT_READY'},
            'Rücknahme nur für eindeutig eigene unvollständige Übernahme')
    for name in data['created']:
        require(list(file_record(within(root,name)))==data['files'][name],f'Rootdatei seit Übernahme verändert {name}')
    if data['state']=='GIT_READY':
        target=root/'.git'
        require(own_toplevel(root) and git(root,'rev-parse','HEAD')==data['stage_head'] and
                not git(root,'status','--porcelain=v1','-uall'),'Gitmetadaten seit Transfer verändert')
        target.rename(journal.parent/'rolled-back.git')
    for name in reversed(data['created']):
        path=within(root,name)
        if name=='AGENTS.md':
            backup=journal.parent/'AGENTS.backup.md'
            require(digest(backup)==data['old_agents'][-1],'Regelsicherung beschädigt')
            temp=journal.parent/'AGENTS.restore'
            with temp.open('xb') as output:
                output.write(backup.read_bytes())
            temp.chmod(data['old_agents'][1])
            temp.replace(path)
        else:
            path.unlink()
            for parent in path.parents:
                if parent==root:
                    break
                try:
                    parent.rmdir()
                except OSError:
                    break
    data['state']='ROLLED_BACK'
    write_atomic(journal,data)
