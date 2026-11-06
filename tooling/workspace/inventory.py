"""Workspace identities and filesystem boundaries."""
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re

CORE = frozenset({'stack', 'admin', 'sodata', 'jenkins', 'plugin', 'topics', 'architecture'})
ID = re.compile(r'[a-z][a-z0-9-]*')
BRANCH = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*')
HTTPS = re.compile(r'https://github\.com/[\w.-]+/[\w.-]+\.git', re.ASCII)


class WorkspaceError(ValueError):
    pass


@dataclass(frozen=True)
class Repository:
    id: str
    path: str
    remote: str | None
    branch: str
    profile: str
    responsibility: str


@dataclass(frozen=True)
class Inventory:
    name: str
    remote: str
    branch: str
    repositories: tuple[Repository, ...]

    def select(self, profile='core', ids=()):
        known = {entry.id for entry in self.repositories}
        if len(set(ids)) != len(ids) or set(ids) - known:
            raise WorkspaceError('Unbekannte oder doppelte Repository-ID')
        return tuple(entry for entry in self.repositories
                     if (entry.id in ids if ids else entry.profile == profile))


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WorkspaceError(f'Doppelter JSON-Schlüssel {key}')
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_pairs)


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value:
        raise WorkspaceError('Ungültiger relativer Pfad')
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or '..' in path.parts
            or path.as_posix() != value or any(part in {'.git', '.runtime'} for part in path.parts)):
        raise WorkspaceError(f'Ungültiger relativer Pfad {value}')
    return path


def within(root, value):
    path = root / relative(value)
    if not path.is_relative_to(root) or path.resolve() != path:
        raise WorkspaceError(f'Symlink oder Pfadflucht {value}')
    return path


def valid_remote(url):
    if isinstance(url, str) and HTTPS.fullmatch(url):
        return True
    # A canonical local bare remote is supported for offline workspaces and tests.
    if isinstance(url, str) and url.startswith('file:///'):
        path = Path(url[7:])
        return path.is_absolute() and path.as_posix() == url[7:] and path.resolve() == path
    return False


def load(path):
    value = read_json(path)
    if set(value) != {'schema_version', 'workspace', 'repositories'} or value['schema_version'] != 1:
        raise WorkspaceError('Unbekanntes Inventarformat')
    workspace = value['workspace']
    if (set(workspace) != {'id', 'name', 'remote', 'branch'} or workspace['id'] != 'workspace'
            or not ID.fullmatch(workspace['name']) or not valid_remote(workspace['remote'])
            or not BRANCH.fullmatch(workspace['branch'])):
        raise WorkspaceError('Ungültige Workspace-Identität')
    entries = tuple(Repository(**item) for item in value['repositories'])
    ids = set()
    paths = []
    for item in entries:
        path = relative(item.path)
        if (len(path.parts) != 1 or not ID.fullmatch(item.path)
                or not ID.fullmatch(item.id) or item.id == 'workspace' or item.id in ids
                or not BRANCH.fullmatch(item.branch) or item.profile not in ('core', 'extended')
                or not isinstance(item.responsibility, str) or not item.responsibility.strip()
                or not (valid_remote(item.remote) or item.id == 'architecture' and item.remote is None)):
            raise WorkspaceError(f'Ungültiger Inventareintrag {item.id}')
        ids.add(item.id)
        if any(path == other or path.is_relative_to(other) or other.is_relative_to(path) for other in paths):
            raise WorkspaceError(f'Überlappender Repositorypfad {path}')
        paths.append(path)
    if {item.id for item in entries if item.profile == 'core'} != CORE:
        raise WorkspaceError('Core benötigt genau sechs Produkte und Architektur')
    return Inventory(workspace['name'], workspace['remote'], workspace['branch'], entries)
