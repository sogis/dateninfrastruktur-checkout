"""Verify root transfer against a populated local Git fixture."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tooling.workspace.adopt import advance, children, plan, rollback
from tooling.workspace.gitops import git
from tooling.workspace.inventory import WorkspaceError

ROOT=Path(__file__).resolve().parents[1]


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base=Path(folder.name).resolve()
        self.root=self.base/'root'
        self.root.mkdir()
        (self.root/'AGENTS.md').write_text('Original\n')
        (self.root/'unrelated').write_text('Existing user file\n')
        self.child=self.root/'product'
        self.child.mkdir()
        git(self.child,'init','-b','main')
        git(self.child,'config','user.name','Test')
        git(self.child,'config','user.email','test@example.invalid')
        (self.child/'file').write_text('tracked\n')
        git(self.child,'add','file')
        git(self.child,'commit','-m','Fixture')
        (self.child/'file').write_text('dirty\n')
        (self.child/'extra').symlink_to('file')
        (self.child/'user.sh').write_text('#!/bin/sh\n')
        (self.child/'user.sh').chmod(0o755)
        self.stage=self.base/'standalone'
        self.stage.mkdir()
        git(self.stage,'init','-b','main')
        git(self.stage,'config','user.name','Test')
        git(self.stage,'config','user.email','test@example.invalid')
        git(self.stage,'remote','add','origin','https://github.com/example/checkout.git')
        (self.stage/'AGENTS.md').write_text('Current\n')
        (self.stage/'.gitignore').write_text('/*\n!/AGENTS.md\n!/.gitignore\n!/workspace\n')
        (self.stage/'workspace').write_text('#!/bin/sh\n')
        (self.stage/'workspace').chmod(0o755)
        git(self.stage,'add','.gitignore','AGENTS.md','workspace')
        git(self.stage,'commit','-m','Workspace')
        self.copy=self.base/'original.md'
        self.copy.write_bytes((self.root/'AGENTS.md').read_bytes())
        self.journal=self.base/'journal.json'
        self.head=git(self.stage,'rev-parse','HEAD')
        self.baseline=children(self.root,['product'])

    def prepare(self):
        return plan(self.root,self.stage,['product'],self.journal,self.head,self.copy)

    def test_resume_after_files(self):
        self.prepare()
        with self.assertRaises(InterruptedError):
            advance(self.journal,interrupt_after='files')
        self.assertFalse((self.root/'.git').exists())
        self.assertEqual(advance(self.journal)['state'],'DONE')
        self.assertEqual(advance(self.journal)['state'],'DONE')
        self.assertEqual(git(self.root,'rev-parse','HEAD'),self.head)
        self.assertEqual(children(self.root,['product']),self.baseline)
        self.assertEqual((self.root/'unrelated').read_text(),'Existing user file\n')

    def test_resume_after_one_file(self):
        self.prepare()
        with self.assertRaises(InterruptedError):
            advance(self.journal,interrupt_after='file')
        self.assertEqual(advance(self.journal)['state'],'DONE')
        self.assertEqual(children(self.root,['product']),self.baseline)

    def test_rollback_owned_files(self):
        self.prepare()
        with self.assertRaises(InterruptedError):
            advance(self.journal,interrupt_after='git')
        rollback(self.journal)
        self.assertEqual((self.root/'AGENTS.md').read_bytes(),self.copy.read_bytes())
        self.assertEqual(children(self.root,['product']),self.baseline)
        self.assertFalse((self.root/'.git').exists())
        self.assertFalse((self.root/'workspace').exists())
        self.assertEqual((self.root/'unrelated').read_text(),'Existing user file\n')

    def test_collision_and_changed_child(self):
        (self.root/'workspace').write_text('foreign\n')
        with self.assertRaisesRegex(WorkspaceError,'Kollision'):
            self.prepare()
        self.assertEqual((self.root/'workspace').read_text(),'foreign\n')
        (self.root/'workspace').unlink()
        self.prepare()
        (self.child/'file').write_text('new user edit\n')
        with self.assertRaisesRegex(WorkspaceError,'Kindrepo'):
            advance(self.journal)
        self.assertFalse((self.root/'.git').exists())
        self.assertEqual((self.child/'file').read_text(),'new user edit\n')


def check_outcome(path):
    data=json.loads(path.read_text())
    assert data['stage']=='DONE' and data['previous_agents_retained']
    assert data['runtime_identity_unchanged'] and data['child_fingerprints_unchanged']
    assert data['root_head']==git(ROOT,'rev-parse','HEAD')
    assert len(data['children'])>=7 and data['root_origin']==git(ROOT,'remote','get-url','origin')
    print('ASSERTIONS=4 SKIP=0')


if __name__=='__main__':
    if len(sys.argv)>1:
        check_outcome(Path(sys.argv[1]))
    else:
        suite=unittest.TestLoader().loadTestsFromTestCase(AdoptionTests)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful() or result.testsRun!=4 or result.skipped:
            raise SystemExit(1)
        print(f'ASSERTIONS={result.testsRun} SKIP=0')
