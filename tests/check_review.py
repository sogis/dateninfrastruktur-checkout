"""Exercise the real review verifier with forged and valid synthetic transcripts."""
import copy
from pathlib import Path
import tempfile
import unittest

from tooling.review.contracts import binding, check_run, command_for, load_task
from tooling.review.runner import metadata
from tooling.workspace.gitops import digest, write_atomic
from tooling.workspace.inventory import WorkspaceError


class ReviewTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.output=self.root/'output'
        self.output.mkdir()
        self.workspace=str(self.root/'workspace')
        self.command=command_for('check',['python3','-m','fixture'],0)
        self.counter_command='python3 counter.py'
        log=self.make_evidence('check.log','ASSERTIONS=1 SKIP=0\n')
        counter=self.make_evidence('counter.log','NEGATIVE REJECTED\n')
        identity=dict(schema_version=1,candidate_id='candidate',specification='synthetic',revision='3',phase='read')
        self.handoff=dict(**identity,source_set_sha256='a'*64,specification_sha256='b'*64,request_sha256='c'*64,
            repositories={'workspace':{'head':'d'*40}},required_checks=['check'],workspace=self.workspace,
            checks={'check':{'argv':['python3','-m','fixture'],'exit':0,'shell_command':self.command,
                             'dependency_fingerprint':'inputs'}},carried={},
            reviewer={'model':'provider/model'})
        path=self.root/'handoff.json'
        write_atomic(path,self.handoff)
        self.expected=binding(path,self.handoff)
        self.runner=dict(exit_code=0,errors=0,model='provider/model',model_provenance_verified=True,
            agent='independent-review',session_id='session',fresh=True,candidate_unchanged=True,original_unchanged=True)
        self.report=dict(**identity,binding=copy.deepcopy(self.expected),reviewer={'runner_run_id':'candidate'},
            integrity=dict(product_unchanged=True,original_workspace_unchanged=True),
            checks=[dict(requirement_id='check',status='PASS',execution='EXECUTED',command_argv=['python3','-m','fixture'],
                         cwd=self.workspace,expected_exit=0,observed_exit=0,assertions_executed=1,required_assertions_skipped=0,
                         started_at_utc='start',finished_at_utc='finish',observation='verified',evidence=log)],
            counterexample=dict(executed=True,hypothesis='counter',expected='reject',observed='rejected',
                command=self.counter_command,cwd=self.workspace,expected_exit=0,observed_exit=0,
                marker='NEGATIVE REJECTED',evidence=counter),
            verdict='ABGENOMMEN',not_executed=[],findings=[],
            code_review=dict(code_correct=True,goal_reached=True,scope_respected=True))
        self.manifest=dict(schema_version=1,run_id='candidate',candidate_id='candidate',files=[log,counter])
        self.events=[self.event(self.command,'ASSERTIONS=1 SKIP=0\n'),self.event(self.counter_command,'NEGATIVE REJECTED\n')]

    def make_evidence(self,name,data):
        path=self.output/name
        path.write_text(data)
        return dict(path=name,bytes=path.stat().st_size,sha256=digest(path))

    def event(self,command,output):
        return dict(type='tool_use',part=dict(tool='shell',state=dict(status='completed',
            input=dict(command=command),output=output,metadata={'metadata':{'exit':0}})))

    def evaluate(self, **override):
        arguments=dict(handoff=self.handoff,expected=self.expected,runner=self.runner,
                       report=self.report,manifest=self.manifest,output=self.output,events=self.events)
        check_run(**(arguments|override))

    def test_real_events_required(self):
        self.evaluate()
        with self.assertRaisesRegex(WorkspaceError,'Shellereignis'):
            self.evaluate(events=self.events[1:])
        with self.assertRaisesRegex(WorkspaceError,'Shellereignis'):
            self.evaluate(events=self.events[:1])
        self.events[0]['part']['state']['input']['workdir']='/wrong/workspace'
        with self.assertRaisesRegex(WorkspaceError,'Shellereignis'):
            self.evaluate()

    def test_revision_model_and_assertions_required(self):
        for override in (dict(report=dict(self.report,revision='2')),dict(runner=dict(self.runner,model='other/model')),
                         dict(runner=dict(self.runner,fresh=False)),dict(runner=dict(self.runner,errors=1))):
            with self.subTest(fields=override.keys()),self.assertRaises(WorkspaceError):
                self.evaluate(**override)
        self.report['checks'][0]['assertions_executed']=0
        with self.assertRaisesRegex(WorkspaceError,'Prüfbeleg'):
            self.evaluate()

    def test_bound_output(self):
        path=self.output/'check.log'
        path.unlink()
        outside=self.root/'external.log'
        outside.write_text('ASSERTIONS=1 SKIP=0\n')
        path.symlink_to(outside)
        with self.assertRaises(WorkspaceError):
            self.evaluate()

    def test_carried_fingerprint(self):
        check=self.report['checks'][0]
        reference={'run_id':'prior','session_id':'prior-session','report_sha256':'a'*64}
        self.handoff['carried']['check']=dict(reference=reference,source=copy.deepcopy(check),dependency_fingerprint='inputs')
        check.update(execution='CARRIED',carried_from=reference,nonimpact_reason='same dependency files and tool')
        self.evaluate(events=self.events[1:])
        self.handoff['checks']['check']['dependency_fingerprint']='changed'
        with self.assertRaisesRegex(WorkspaceError,'ungebunden'):
            self.evaluate(events=self.events[1:])

    def test_standalone_session_metadata(self):
        data={'messages':[{'type':'assistant','agent':'independent-review','model':{'providerID':'direct','id':'required'}},
                          {'type':'user','text':'untrusted claims do not count'}]}
        self.assertEqual(metadata(data),{('direct/required','independent-review')})

    def test_task_manifest(self):
        manifest=dict(schema_version=1,specification='synthetic',revision='3',
            files=['contracts/normative-files.json','contracts/phase-checks.json','review.md'])
        write_atomic(self.root/'contracts/normative-files.json',manifest)
        write_atomic(self.root/'contracts/phase-checks.json',dict(schema_version=1,specification='synthetic',
            revision='3',phases={'read':['check']}))
        (self.root/'review.md').write_text('Instructions\n')
        write_atomic(self.root/'.work/requests/read.json',dict(schema_version=1,specification='synthetic',
            revision='3',phase='read',review_prompt='review.md',checks={'check':{}}))
        first=load_task(self.root,'read')
        self.assertEqual(first['required'],['check'])
        (self.root/'review.md').write_text('Different instructions\n')
        self.assertNotEqual(load_task(self.root,'read')['digest'],first['digest'])
        manifest['files'].append('../outside')
        write_atomic(self.root/'contracts/normative-files.json',manifest)
        with self.assertRaises(WorkspaceError):
            load_task(self.root,'read')


if __name__=='__main__':
    suite=unittest.TestLoader().loadTestsFromTestCase(ReviewTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.testsRun!=6 or result.skipped:
        raise SystemExit(1)
    print(f'ASSERTIONS={result.testsRun} SKIP=0')
