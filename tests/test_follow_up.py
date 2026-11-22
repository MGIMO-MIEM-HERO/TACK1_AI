import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

import test_quality_contract as fixture
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from checkpoint import ROOT,write_state
from follow_up import acknowledge,deadline,inspect,instant,result_version,zone
from project_tool import load,report
from quality import state_hash
from start import restore
from validate_project import validate

NOW=instant('2026-11-19T10:00:00+03:00')


class FollowUpTests(unittest.TestCase):
    setUp=fixture.QualityContractTests.setUp
    complete_record=fixture.QualityContractTests.complete_record
    run_cli=fixture.QualityContractTests.run_cli

    def setup_follow_up(self):
        self.complete_record()
        self.project['timezone']='Europe/Moscow'
        self.project['commitments']=[{'commitment_id':'C1','status':'agreed','owner':'Fixture owner',
            'metric':'Tasks complete','due':'2026-11-18','agreement_reference':'Authored unit fixture, not an actual approval',
            'review_trigger':'Owner reviews results; no automatic completion'}]
        self.project['metric_results']=[{'result_id':'R1','commitment_id':'C1','metric':'Tasks complete','value':'2','unit':'tasks',
            'observed_at':'2026-11-18T00:00:00Z','data_origin':'synthetic','evidence_ids':['E1'],
            'summary':'Synthetic contract fixture; no market effect'}]
        write_state(self.path,self.project)
        return self.project

    def inspect(self,at=NOW):return inspect(self.project,self.path,ROOT,at=at)

    def test_date_deadline_includes_the_whole_local_day(self):
        self.setup_follow_up();self.project['commitments'][0]['due']='2026-11-19'
        self.assertFalse(self.inspect(instant('2026-11-19T23:59:59+03:00'))['overdue_commitments'])
        self.assertEqual(len(self.inspect(instant('2026-11-20T00:00:00+03:00'))['overdue_commitments']),1)

    def test_timestamp_offsets_and_exact_instant_boundary(self):
        self.setup_follow_up();self.project['commitments'][0]['due']='2026-11-19T08:00:00Z'
        self.assertFalse(self.inspect(instant('2026-11-19T11:00:00+03:00'))['overdue_commitments'])
        self.assertEqual(len(self.inspect(instant('2026-11-19T11:00:01+03:00'))['overdue_commitments']),1)

    def test_completed_cancelled_and_unconfirmed_are_not_overdue(self):
        self.setup_follow_up()
        for status in ('completed','cancelled','proposed'):
            self.project['commitments'][0]['status']=status
            self.assertFalse(self.inspect()['overdue_commitments'])
        self.project['commitments'][0]['status']='agreed';self.project['commitments'][0].pop('agreement_reference')
        self.assertFalse(self.inspect()['overdue_commitments'])
        self.assertEqual(self.inspect()['commitments'][0]['kind'],'unconfirmed')

    def test_blocked_agreed_commitment_is_overdue_only_after_deadline(self):
        self.setup_follow_up();c=self.project['commitments'][0];c['status']='blocked'
        self.assertEqual(self.inspect()['commitments'][0]['kind'],'overdue')
        c['due']='2026-12-01'
        self.assertEqual(self.inspect()['commitments'][0]['kind'],'blocked')
        self.assertFalse(self.inspect()['overdue_commitments'])

    def test_missing_zone_or_unreadable_deadline_requires_clarification(self):
        self.setup_follow_up();self.project.pop('timezone')
        self.assertFalse(self.inspect()['overdue_commitments'])
        self.assertEqual(self.inspect()['commitments'][0]['kind'],'deadline_needs_clarification')
        self.project['commitments'][0]['due']='after the next meeting'
        self.assertFalse(self.inspect()['overdue_commitments'])
        self.project['timezone']='Europe/Moscow';self.project['commitments'][0]['due']='20261119'
        self.assertEqual(self.inspect()['commitments'][0]['kind'],'deadline_needs_clarification')

    def test_no_project_zone_is_needed_for_an_explicit_offset(self):
        self.setup_follow_up();self.project.pop('timezone');self.project['commitments'][0]['due']='2026-11-18T12:00:00+03:00'
        self.assertEqual(len(self.inspect()['overdue_commitments']),1)

    def test_invalid_zone_is_not_silently_treated_as_utc(self):
        self.setup_follow_up();self.project['timezone']='Mars/Unknown'
        self.assertTrue(any(q['question_id']=='timezone' for q in self.inspect()['human_questions']))
        self.assertFalse(self.inspect()['overdue_commitments'])

    def test_moscow_fallback_is_portable_and_does_not_fake_historical_rules(self):
        with patch('follow_up.ZoneInfo',side_effect=ZoneInfoNotFoundError):
            self.assertEqual(deadline('2026-11-19','Europe/Moscow')[0].utcoffset().total_seconds(),10800)
            with self.assertRaises(ValueError):deadline('2010-03-28','Europe/Moscow')
            with self.assertRaises(ValueError):zone('Europe/Paris')
        self.assertEqual(zone('+05:30').utcoffset(None).total_seconds(),19800)
        with self.assertRaises(ValueError):zone('+25:00')

    def test_naive_clock_is_rejected_and_local_due_can_use_explicit_zone(self):
        self.setup_follow_up();self.project['commitments'][0]['due']='2026-11-19T09:00:00'
        self.assertEqual(len(self.inspect()['overdue_commitments']),1)
        with self.assertRaises(ValueError):self.inspect(datetime(2026,11,19))

    def test_repeated_opening_is_read_only_and_has_no_duplicate_questions(self):
        self.setup_follow_up();before=self.path.read_bytes();original=copy.deepcopy(self.project)
        a=restore(self.path,at=NOW)['follow_up'];b=restore(self.path,at=NOW)['follow_up']
        self.assertEqual(a,b);self.assertEqual(self.path.read_bytes(),before);self.assertEqual(self.project,original)
        self.assertEqual(len(a['human_questions']),len({q['question_id'] for q in a['human_questions']}))

    def test_acknowledgement_is_versioned_idempotent_and_not_approval(self):
        self.setup_follow_up();before_hash=state_hash(self.project,self.path,ROOT)
        result=acknowledge(self.project,self.path,ROOT,['R1'],'Agent','Read the synthetic fixture; owner interpretation pending')
        self.assertEqual(result['recorded'],['R1']);self.project=load(self.path)
        self.assertEqual(state_hash(self.project,self.path,ROOT),before_hash)
        before=self.path.read_bytes();log_before=(self.root/'ledger.jsonl').read_bytes()
        self.assertEqual(acknowledge(self.project,self.path,ROOT,['R1'],'Agent','Already read')['recorded'],[])
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual((self.root/'ledger.jsonl').read_bytes(),log_before)
        after=instant(self.project['follow_up_reviews'][-1]['reviewed_at'])
        self.assertFalse(self.inspect(after)['new_results'])
        self.assertTrue(any(q['question_id']=='result:R1' for q in self.inspect(after)['human_questions']))
        self.assertEqual(self.project['commitments'][0]['status'],'agreed')
        self.assertIsNone(self.project.get('chosen_option_id'))

    def test_result_or_source_change_resurfaces_an_old_review(self):
        self.setup_follow_up();acknowledge(self.project,self.path,ROOT,['R1'],'Agent','Read only');self.project=load(self.path)
        after=instant(self.project['follow_up_reviews'][-1]['reviewed_at'])
        self.project['metric_results'][0]['value']='3'
        row=self.inspect(after)['new_results'][0]
        self.assertTrue(row['previously_reviewed_version'])
        self.project['metric_results'][0]['value']='2'
        (self.root/'source.md').write_text('Changed source',encoding='utf-8')
        self.assertTrue(self.inspect(after)['new_results'])
        self.assertTrue(self.inspect()['source_alerts'])

    def test_human_decision_is_bound_to_a_result_and_review_trigger_version(self):
        self.setup_follow_up();r=self.project['metric_results'][0]
        version=result_version(self.project,self.path,ROOT,r)
        r['human_decision']={'reference':'Authored test decision, not a real owner response','version_hash':version}
        self.assertFalse(any(q['question_id']=='result:R1' for q in self.inspect()['human_questions']))
        self.project['commitments'][0]['due']='2026-12-01'
        self.assertEqual(result_version(self.project,self.path,ROOT,r),version)
        self.project['commitments'][0]['review_trigger']='A different decision criterion'
        self.assertTrue(any(q['question_id']=='result:R1' for q in self.inspect()['human_questions']))

    def test_status_expiry_and_source_change_have_explicit_dependency_reasons(self):
        self.setup_follow_up();self.project['sources'][0]['valid_until']='2026-11-18'
        result=self.inspect();self.assertTrue(any('valid_until' in reason for a in result['source_alerts'] for reason in a['reasons']))
        self.project['evidence'][0]['status']='withdrawn'
        result=self.inspect()
        self.assertEqual({a['evidence_id'] for a in result['evidence_alerts']},{'E1','E2'})
        self.assertTrue(all(a['impact']['option_ids'] for a in result['evidence_alerts']))

    def test_old_access_date_alone_does_not_make_a_source_stale(self):
        self.setup_follow_up();self.project['sources'][0]['accessed_at']='2020-01-01'
        self.assertFalse(self.inspect()['source_alerts'])

    def test_synthetic_or_future_result_cannot_be_acknowledged_as_real(self):
        self.setup_follow_up();r=self.project['metric_results'][0];r['data_origin']='real'
        self.assertTrue(self.inspect()['metric_results'][0]['support_problems'])
        self.project['strategy_review']['state_hash']=state_hash(self.project,self.path,ROOT)
        with self.assertRaises(ValueError):report(self.project,self.path,final=True)
        with self.assertRaises(ValueError):acknowledge(self.project,self.path,ROOT,['R1'],'Agent','Bad support')
        r['data_origin']='synthetic';r['observed_at']='2099-01-01T00:00:00Z'
        self.assertTrue(self.inspect()['metric_results'][0]['support_problems'])

    def test_malformed_ids_receipts_and_metric_mismatch_are_rejected(self):
        self.setup_follow_up();original=copy.deepcopy(self.project)
        for mutate in (lambda p:p['metric_results'][0].update(metric='Other metric'),
                       lambda p:p['metric_results'][0].update(observed_at='2026-11-18T10:00'),
                       lambda p:p['metric_results'][0].update(evidence_ids=['FAKE']),
                       lambda p:p['metric_results'][0].update(commitment_id='FAKE'),
                       lambda p:p.update(follow_up_reviews=[{}]),
                       lambda p:p['commitments'].append(copy.deepcopy(p['commitments'][0]))):
            p=copy.deepcopy(original);mutate(p);self.assertTrue(validate(p))

    def test_legacy_missing_status_is_visible_without_fake_overdue(self):
        self.setup_follow_up();self.project['metric_results']=[];c=self.project['commitments'][0]
        c.pop('status');c.pop('commitment_id')
        result=self.inspect()
        self.assertFalse(result['overdue_commitments']);self.assertEqual(result['commitments'][0]['object_ref'],'/commitments/0')

    def test_report_has_follow_up_and_cli_cannot_overwrite_inputs(self):
        self.setup_follow_up();self.project['strategy_review']['state_hash']=state_hash(self.project,self.path,ROOT);write_state(self.path,self.project)
        self.assertIn('Сопровождение после решения',report(self.project,self.path))
        with self.assertRaisesRegex(ValueError, 'Required decision stress'):
            report(self.project,self.path,final=True)
        before=self.path.read_bytes()
        result=self.run_cli('follow_up.py','report',self.path,'--as-of','2026-11-19T10:00:00+03:00','--out',self.path)
        self.assertEqual(result.returncode,1);self.assertEqual(self.path.read_bytes(),before)

    def test_dst_ambiguity_is_never_silently_resolved(self):
        try:ZoneInfo('America/New_York')
        except ZoneInfoNotFoundError:
            with self.assertRaises(ValueError):deadline('2026-11-01T01:30:00','America/New_York')
        else:
            with self.assertRaises(ValueError):deadline('2026-11-01T01:30:00','America/New_York')
            with self.assertRaises(ValueError):deadline('2026-03-08T02:30:00','America/New_York')
        a=deadline('2026-11-01T01:30:00-04:00',None)[0]
        b=deadline('2026-11-01T01:30:00-05:00',None)[0]
        self.assertEqual((b-a).total_seconds(),3600)

    def test_metric_source_expiry_uses_the_follow_up_local_replay_day(self):
        self.setup_follow_up();self.project['sources'][0]['valid_until']='2026-11-18'
        # Same UTC date as expiry, but already the next day in Moscow.
        result=self.inspect(instant('2026-11-18T22:00:00Z'))
        self.assertTrue(any('expired' in p for p in result['metric_results'][0]['support_problems']))
        result=self.inspect(instant('2026-11-18T10:00:00Z'))
        self.assertFalse(any('expired' in p for p in result['metric_results'][0]['support_problems']))

    def test_future_read_receipt_is_not_applied_to_an_earlier_clock(self):
        self.setup_follow_up();r=self.project['metric_results'][0]
        self.project['follow_up_reviews']=[{'result_id':'R1','version_hash':result_version(self.project,self.path,ROOT,r),
            'reviewed_at':'2026-11-20T10:00:00+03:00','reviewer':'Fixture agent','note':'Future relative to replay clock'}]
        row=self.inspect()['new_results'][0]
        self.assertTrue(row['receipt_after_clock']);self.assertFalse(row['reviewed'])


if __name__=='__main__':unittest.main()
