"""Smoke tests for the installed workspace layout."""
from pathlib import Path
import subprocess
import sys
import tempfile

from tooling.workspace.gitops import git, root_allowed
from tooling.workspace.inventory import load

ROOT=Path(__file__).resolve().parents[1]


def review_path():
    stack=ROOT/'dateninfrastruktur-dev-stack'
    removed=('review-phase.py','review-phase.sh','review_gate.py','reviewer-agent.md','test_review_gate.py','test_review_g0.py')
    assert all(not (stack/'scripts/management'/name).exists() for name in removed)
    assert not (stack/'scripts/local_cutover_g5.py').exists()
    assert not (ROOT/'checkout.sh').exists()
    assert (ROOT/'tooling/review/runner.py').is_file()
    assert len(list(ROOT.glob('repositories.*')))==1
    assert (ROOT/'.opencode/agents/independent-review.md').is_file()
    for repo in load(ROOT/'repositories.json').select():
        folder=ROOT/repo.path
        if repo.id=='architecture':
            continue
        assert '../AGENTS.md' in (folder/'AGENTS.md').read_text()
    print('ASSERTIONS=7 SKIP=0')


def git_layout():
    result=subprocess.run([sys.executable,str(ROOT/'workspace'),'verify'],cwd=ROOT,
                          capture_output=True,text=True,check=True)
    assert 'Workspace-Grenzen geprüft' in result.stdout
    assert Path(git(ROOT,'rev-parse','--show-toplevel'))==ROOT
    stack=ROOT/'dateninfrastruktur-dev-stack'
    assert Path(git(stack,'rev-parse','--show-toplevel'))==stack
    assert git(ROOT,'rev-parse','HEAD')!=git(stack,'rev-parse','HEAD')
    assert all(root_allowed(f) for f in git(ROOT,'ls-files').splitlines())
    with tempfile.TemporaryDirectory() as temp:
        result=subprocess.run([sys.executable,str(ROOT/'workspace'),'verify'],cwd=temp,
                              capture_output=True,text=True,check=True)
        assert 'Workspace-Grenzen geprüft' in result.stdout
    print('ASSERTIONS=6 SKIP=0')


if __name__=='__main__':
    {'review':review_path,'git':git_layout}[sys.argv[1]]()
