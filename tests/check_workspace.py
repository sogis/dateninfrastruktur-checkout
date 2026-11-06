"""Focused tests on real temporary Git repositories."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

from tooling.workspace.gitops import clone_exact, clone_missing, fingerprint, git, inspect, source_set, sync, verify_root, write_atomic
from tooling.workspace.inventory import WorkspaceError, load, read_json, within

PROJECT = Path(__file__).resolve().parents[1]


def initialize(path):
    path.mkdir()
    git(path,'init','-b','main')
    git(path,'config','user.email','test@example.invalid')
    git(path,'config','user.name','Workspace Test')
    (path/'hello').write_text('initial\n')
    git(path,'add','hello')
    git(path,'commit','-m','Fixture')


def commit(path, content):
    (path/'hello').write_text(content)
    git(path,'add','hello')
    git(path,'commit','-m','Change')


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name).resolve()
        self.origin=self.base/'origin'
        initialize(self.origin)
        self.bare=self.base/'remote.git'
        git(self.base,'clone','--bare','--no-hardlinks',str(self.origin),str(self.bare))
        self.root=self.base/'workspace'
        self.root.mkdir()
        git(self.root,'init','-b','main')
        git(self.root,'config','user.email','test@example.invalid')
        git(self.root,'config','user.name','Workspace Test')
        git(self.root,'remote','add','origin',self.bare.as_uri())
        for name in ('.gitignore','.opencode/agents/independent-review.md'):
            target=self.root/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((PROJECT/name).read_bytes())
        self.data=read_json(PROJECT/'repositories.json')
        self.data['workspace']['remote']=self.bare.as_uri()
        for entry in self.data['repositories']:
            if entry['remote'] is not None:
                entry['remote']=self.bare.as_uri()
        self.inventory_path=self.root/'repositories.json'
        write_atomic(self.inventory_path,self.data)
        self.inv=load(self.inventory_path)
        self.entry=self.inv.select(ids=('admin',))[0]
        self.child=self.root/self.entry.path
        git(self.root,'add','.gitignore','.opencode','repositories.json')
        git(self.root,'commit','-m','Workspace')

    def test_inventory(self):
        self.assertEqual(len(self.inv.select()),7)
        self.assertEqual(len(self.inv.select('extended')),4)
        for replacement in ('../escape','/absolute','admin/nested','dateninfrastruktur-sodata'):
            with self.subTest(path=replacement):
                broken=copy.deepcopy(self.data)
                broken['repositories'][1]['path']=replacement
                write_atomic(self.inventory_path,broken)
                with self.assertRaises(WorkspaceError):
                    load(self.inventory_path)
        broken=copy.deepcopy(self.data)
        broken['repositories'][1]['remote']='https://user:password@github.com/org/repo.git'
        write_atomic(self.inventory_path,broken)
        with self.assertRaises(WorkspaceError):
            load(self.inventory_path)
        self.child.symlink_to(self.origin,target_is_directory=True)
        with self.assertRaises(WorkspaceError):
            within(self.root,self.entry.path)

    def test_sync(self):
        self.assertEqual(clone_missing(self.root,self.entry),'CLONED')
        initial=fingerprint(self.child)
        commit(self.origin,'upstream')
        git(self.origin,'push',self.bare.as_uri(),'main')
        self.assertEqual(clone_missing(self.root,self.entry),'PRESENT')
        self.assertEqual(fingerprint(self.child),initial)
        (self.child/'untracked').write_text('user work')
        before=fingerprint(self.child)
        with self.assertRaises(WorkspaceError):
            sync(self.root,self.entry)
        self.assertEqual(fingerprint(self.child),before)
        (self.child/'untracked').unlink()
        self.assertEqual(sync(self.root,self.entry),'FAST_FORWARD')
        self.assertEqual((self.child/'hello').read_text(),'upstream')
        git(self.child,'config','user.email','test@example.invalid')
        git(self.child,'config','user.name','Workspace Test')
        commit(self.child,'ahead')
        before=fingerprint(self.child)
        self.assertEqual(sync(self.root,self.entry),'AHEAD')
        self.assertEqual(fingerprint(self.child),before)
        commit(self.origin,'divergent')
        git(self.origin,'push',self.bare.as_uri(),'main')
        with self.assertRaisesRegex(WorkspaceError,'divergiert'):
            sync(self.root,self.entry)
        self.assertEqual(fingerprint(self.child),before)
        git(self.child,'branch','--unset-upstream')
        with self.assertRaises(WorkspaceError):
            sync(self.root,self.entry)
        git(self.child,'checkout','--detach')
        with self.assertRaises(WorkspaceError):
            sync(self.root,self.entry)
        git(self.child,'remote','set-url','origin',self.origin.as_uri())
        self.assertEqual(inspect(self.root,self.entry)['state'],'REMOTE_MISMATCH')
        with self.assertRaises(WorkspaceError):
            clone_missing(self.root,self.entry)

    def test_boundaries(self):
        self.assertTrue(verify_root(self.root,self.inv))
        self.child.mkdir()
        with self.assertRaisesRegex(WorkspaceError,'Toplevel'):
            verify_root(self.root,self.inv)
        self.child.rmdir()
        clone_missing(self.root,self.entry)
        self.assertTrue(verify_root(self.root,self.inv))
        git(self.root,'add','-f',self.entry.path)
        with self.assertRaises(WorkspaceError):
            verify_root(self.root,self.inv)
        git(self.root,'rm','--cached','-f',self.entry.path)
        (self.root/'other').write_text('unrelated')
        git(self.root,'add','-f','other')
        with self.assertRaises(WorkspaceError):
            verify_root(self.root,self.inv)
        git(self.root,'rm','--cached','-f','other')
        (self.root/'tooling').mkdir()
        (self.root/'tooling'/'pointer').symlink_to(self.origin/'hello')
        git(self.root,'add','tooling/pointer')
        with self.assertRaises(WorkspaceError):
            verify_root(self.root,self.inv)

    def test_snapshot(self):
        clone_missing(self.root,self.entry)
        capture=source_set(self.root,self.inv,[self.entry])
        row=capture['repositories'][self.entry.id]
        target=self.base/'clone'
        clone_exact(self.child,target,row)
        self.assertEqual(git(target,'rev-parse','HEAD'),row['head'])
        self.assertFalse((target/'.git/objects/info/alternates').exists())
        self.assertNotEqual((target/'.git/HEAD').stat().st_ino,(self.child/'.git/HEAD').stat().st_ino)
        before=fingerprint(target)
        (target/'hello').chmod(0o755)
        self.assertNotEqual(fingerprint(target),before)
        (target/'hello').unlink()
        (target/'hello').symlink_to(self.origin/'hello')
        self.assertEqual(fingerprint(target)[1]['hello'][0],'symlink')
        self.assertEqual(git(self.child,'status','--porcelain'),'')
        (self.child/'user').write_text('exclude')
        with self.assertRaises(WorkspaceError):
            source_set(self.root,self.inv,[self.entry])
        self.assertEqual(source_set(self.root,self.inv,[self.entry],allow_untracked=True),capture)


if __name__=='__main__':
    selected=sys.argv[1]
    suite=unittest.TestLoader().loadTestsFromName(f'WorkspaceTests.test_{selected}',sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.testsRun!=1 or result.skipped:
        sys.exit(1)
    print('ASSERTIONS=1 SKIP=0')
