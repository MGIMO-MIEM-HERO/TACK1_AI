"""Concrete conditions on existing answer_branches, not a second question registry."""
import json
import math
import re

from stress_test import nonempty, strings


def validate_gap(gap, base):
    errors, ids, signatures, fallbacks = [], set(), set(), 0
    branches = gap.get('answer_branches', [])
    if not isinstance(branches, list): return ['Concrete answer_branches must be an array']
    if gap.get('impact') == 'context' and not branches: return []
    method_items = gap.get('methods', [])
    methods = {m['method_id'] for m in method_items if isinstance(m, dict) and nonempty(m.get('method_id'))} if isinstance(method_items, list) else set()
    def refs(obj, required=False):
        values = obj.get('evidence_ids')
        if not strings(values) or len(values) != len(set(values)) or (required and not values):
            errors.append('Branch evidence_ids must be distinct IDs, nonempty for a known observation/threshold')
        elif not set(values) <= set(base['evidence_ids']): errors.append('Branch references unknown evidence')
    for branch in branches:
        if not isinstance(branch, dict): errors.append('Concrete branch must be an object'); continue
        bid = branch.get('branch_id')
        if not nonempty(bid) or bid in ids: errors.append('branch_id must be unique text per question')
        if nonempty(bid): ids.add(bid)
        if not nonempty(branch.get('next_step')): errors.append('Each branch needs a concrete next_step')
        c = branch.get('condition')
        if not isinstance(c, dict): errors.append('Each branch needs a verifiable condition'); continue
        kind = c.get('kind')
        if kind == 'insufficient_data':
            fallbacks += 1
            if branch.get('option_ids') != []: errors.append('Insufficient-data branch cannot select an alternative')
            if set(c) != {'kind'}: errors.append('Insufficient-data condition must not contain invented observations')
            continue
        if kind not in ('feasibility', 'observation'):
            errors.append('Branch kind must be feasibility/observation/insufficient_data'); continue
        for key in ('indicator', 'criterion'):
            if not nonempty(c.get(key)): errors.append('Branch condition needs ' + key)
        if not nonempty(c.get('method_id')) or c['method_id'] not in methods:
            errors.append('Branch condition must name an existing method to obtain/check the data')
        if kind == 'feasibility':
            requirements = c.get('requirements')
            if not isinstance(requirements, list) or not requirements:
                errors.append('Feasibility branch needs explicit option/outcome requirements'); continue
            opts = set()
            for req in requirements:
                if not isinstance(req, dict): errors.append('Feasibility requirement must be an object'); continue
                oid = req.get('option_id')
                if not nonempty(oid) or oid not in base['option_ids'] or oid in opts:
                    errors.append('Feasibility requirements need distinct registered option IDs')
                if nonempty(oid): opts.add(oid)
                if req.get('outcome') not in ('feasible', 'infeasible'):
                    errors.append('Feasibility requirement must be feasible/infeasible; unknown goes to insufficient_data')
            signature = json.dumps(sorted((r['option_id'], r['outcome']) for r in requirements
                                          if isinstance(r, dict) and nonempty(r.get('option_id')) and nonempty(r.get('outcome'))))
        else:
            state = c.get('assessment')
            if state not in ('met', 'not_met', 'unknown'): errors.append('Observation assessment must be met/not_met/unknown')
            if not nonempty(c.get('rationale')): errors.append('Observation needs a rationale tied to the criterion')
            refs(c, state in ('met', 'not_met'))
            thresholds = c.get('thresholds')
            if not isinstance(thresholds, list): errors.append('Observation needs explicit thresholds (empty for a nonnumeric condition)'); thresholds = []
            if nonempty(c.get('criterion')) and re.search(r'(?<!\w)[+-]?\d+(?:[.,]\d+)?(?!\w)', c['criterion']) and not thresholds:
                errors.append('Numeric decision criterion needs an explicit threshold with a basis')
            for threshold in thresholds:
                if not isinstance(threshold, dict): errors.append('Threshold must be an object'); continue
                value = threshold.get('value')
                try: finite = type(value) in (int, float) and math.isfinite(value)
                except OverflowError: finite = False
                if not finite: errors.append('Threshold value must be a finite number')
                for key in ('metric', 'unit', 'rationale'):
                    if not nonempty(threshold.get(key)): errors.append('Threshold needs ' + key)
                if threshold.get('basis') not in ('owner_agreed', 'empirical', 'derived'):
                    errors.append('Decision thresholds need an agreed, empirical or derived basis; a proposal cannot trigger a choice')
                if threshold.get('basis') == 'owner_agreed' and not nonempty(threshold.get('agreement_reference')):
                    errors.append('Owner-agreed threshold needs an actual agreement reference')
                refs(threshold, True)
            signature = json.dumps([c.get('indicator'), c.get('criterion')], ensure_ascii=False)
        if signature in signatures: errors.append('Duplicate branch conditions do not distinguish alternatives')
        signatures.add(signature)
    if fallbacks != 1 or len(branches) - fallbacks < 2:
        errors.append('Significant research needs two alternative conditions and exactly one insufficient-data branch')
    return errors


def resolve(project, path, root, review):
    from feasibility import inspect as inspect_feasibility
    from quality import FACTS, support_blockers
    by_id = {e['evidence_id']: e for e in project['evidence']}
    sources = {s['source_id']: s for s in project['sources']}
    feasibility = inspect_feasibility(project, path, root)
    available = feasibility['status'] == 'review_record_complete' and feasibility.get('context') == review['context']
    outcomes = {r['option_id']: r for r in feasibility['assessments']} if available else {}
    used, blockers, resolutions = set(), [], []

    def factual(refs, *, threshold_basis=None):
        for eid in refs:
            e = by_id[eid]
            if e['claim_type'] not in FACTS: continue
            pending, seen = [eid], set()
            while pending:
                key = pending.pop()
                if key not in seen:
                    seen.add(key); pending.extend(by_id[key].get('related_evidence_ids', []))
            synthetic = any(sources[s].get('synthetic') or sources[s]['kind'] in ('synthetic', 'model_respondent')
                            or sources[s].get('evidence_scope') == 'simulation'
                            for key in seen for s in by_id[key]['source_ids'])
            if review['context'] == 'live_project' and synthetic: continue
            if threshold_basis == 'empirical' and (e['claim_type'] != 'measured_fact' or e.get('claim_scope') != 'project_observation'):
                continue
            if threshold_basis == 'owner_agreed' and e.get('claim_scope') != 'owner_input': continue
            if threshold_basis in ('owner_agreed', 'derived') and e['claim_type'] not in ('source_fact', 'measured_fact'): continue
            return True
        return False

    for gap in review['gaps']:
        branches = gap['answer_branches']
        if gap['impact'] == 'context' and not branches:
            resolutions.append({'question_id': gap['question_id'], 'status': 'not_applicable', 'branch_id': None,
                                'option_ids': [], 'conditions': [], 'next_step': 'Контекстный вопрос отложен; нет выбора альтернативы.'})
            continue
        fallback = next(b for b in branches if b['condition']['kind'] == 'insufficient_data')
        conditions, assumptions = [], []
        for branch in branches:
            c = branch['condition']; kind = c['kind']
            if kind == 'insufficient_data': continue
            if kind == 'feasibility':
                states = []
                details = []
                for req in c['requirements']:
                    row = outcomes.get(req['option_id'])
                    actual = row['outcome'] if row else 'unknown'
                    states.append('unknown' if actual == 'unknown' else 'met' if actual == req['outcome'] else 'not_met')
                    details.append(req['option_id'] + ': ' + actual + '; требуется ' + req['outcome'])
                    if row: assumptions.extend(row['assumptions'])
                state = 'not_met' if 'not_met' in states else 'unknown' if 'unknown' in states else 'met'
                reason = '; '.join(details)
                if not available: reason += '; нужна актуальная проверка осуществимости в том же контексте'
                refs = []
            else:
                state = c['assessment']; refs = c['evidence_ids']; used.update(refs)
                reason = c['rationale']
                if state != 'unknown' and not factual(refs):
                    blockers.append(gap['question_id'] + ': a known branch condition needs factual evidence, not a hypothesis or synthetic live result')
                    state = 'unknown'
                for threshold in c['thresholds']:
                    used.update(threshold['evidence_ids'])
                    if not factual(threshold['evidence_ids'], threshold_basis=threshold['basis']):
                        blockers.append(gap['question_id'] + ': threshold basis lacks appropriate factual evidence')
                        state = 'unknown'
                support = support_blockers(project, path, root,
                    set(refs) | {eid for t in c['thresholds'] for eid in t['evidence_ids']}, 'Research branch support')
                if support:
                    blockers.extend(support); state = 'unknown'
                    reason += '; основания требуют пересмотра'
            method = next(m for m in gap['methods'] if m['method_id'] == c['method_id'])
            if method['access'] != 'available' or method['adequacy'] != 'sufficient':
                state = 'unknown'
                reason += '; доступность или достаточность способа проверки не подтверждена'
            conditions.append({'branch_id': branch['branch_id'], 'state': state, 'reason': reason,
                               'evidence_ids': refs, 'kind': kind,
                               'feasibility_review_id': feasibility.get('review_id') if kind == 'feasibility' else None})
        met = [r for r in conditions if r['state'] == 'met']
        unresolved = any(r['state'] == 'unknown' for r in conditions)
        matched = len(met) == 1 and not unresolved
        selected = next(b for b in branches if b['branch_id'] == met[0]['branch_id']) if matched else fallback
        if len(met) > 1: reason = 'Несколько условий выполнены: противоречие или пересечение; выбор не определён.'
        elif unresolved: reason = 'Не все конкурирующие условия проверены; сначала устранить неизвестное.'
        elif not met: reason = 'Ни одно условие альтернатив не выполнено; уточнить рамку или получить недостающие данные.'
        else: reason = 'Ровно одно условие выполнено, остальные проверены и не выполнены.'
        if gap['status'] == 'answered' and not matched:
            blockers.append(gap['question_id'] + ': cannot mark a decision-changing question answered while its branch is undetermined')
        resolutions.append({'question_id': gap['question_id'], 'status': 'matched' if matched else 'insufficient_data',
                            'branch_id': selected['branch_id'], 'option_ids': selected['option_ids'] if matched else [],
                            'consequence': selected['consequence'], 'next_step': selected['next_step'],
                            'reason': reason, 'conditions': conditions, 'assumptions': sorted(set(assumptions))})
    blockers.extend(support_blockers(project, path, root, used, 'Research branch support'))
    return resolutions, sorted(set(blockers))
