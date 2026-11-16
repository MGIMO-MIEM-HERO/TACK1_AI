"""Explicit research contracts. Checks records and provenance, not the truth of prose."""
import hashlib
import json
import re
from pathlib import Path

FACTS = {'source_fact', 'measured_fact', 'association', 'qualitative_signal'}
SCOPES = {'source_description', 'owner_input', 'project_observation', 'market_demand', 'causal_effect'}
SOURCE_KINDS = {'document', 'table', 'website', 'interview', 'synthetic', 'tool_output',
                'model_respondent', 'agent_note'}
REVIEW_FIELDS = ('comparison', 'strongest_objection', 'reversal_condition', 'evidence_limits')


def text(value):
    return isinstance(value, str) and bool(value.strip())


def state_hash(project, path=None, root=None):
    # Checkpoints and dates are operational records, not a new strategy.
    payload = {k: v for k, v in project.items() if k not in ('checkpoints', 'updated_at', 'strategy_review')}
    if path is not None:
        from checkpoint import fingerprint
        base = path.parent if project.get('path_base') == 'project' else root
        payload = {**payload, '_source_content': {
            source['source_id']: fingerprint(source.get('snapshot_path') or source['url_or_path'], base)
            for source in project['sources']}}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def validate_fields(project):
    errors = []
    requirement = project.get('research_requirements')
    if requirement is not None:
        if not isinstance(requirement, dict) or not text(requirement.get('rationale')) or not isinstance(requirement.get('source_kinds'), list):
            errors.append('research_requirements needs source_kinds and a rationale')
        elif any(not isinstance(k, str) or k not in SOURCE_KINDS for k in requirement['source_kinds']):
            errors.append('research_requirements contains an unknown source kind')
    source_ids = {s['source_id'] for s in project.get('sources', []) if isinstance(s, dict) and isinstance(s.get('source_id'), str)}
    evidence_ids = {e['evidence_id'] for e in project.get('evidence', []) if isinstance(e, dict) and isinstance(e.get('evidence_id'), str)}
    for source in project.get('sources', []):
        if not isinstance(source, dict):
            continue
        if 'content_kind' in source and source['content_kind'] not in ('page', 'excerpt', 'summary'):
            errors.append('source.content_kind must be page/excerpt/summary')
        if 'evidence_scope' in source and source['evidence_scope'] not in (
                'general_guidance', 'market_observation', 'project_observation', 'owner_input', 'simulation', 'description'):
            errors.append('source.evidence_scope is unknown')
        checks = source.get('quote_checks')
        if checks is not None and (not isinstance(checks, list) or any(
                not isinstance(q, dict) or not text(q.get('excerpt')) or type(q.get('found')) is not bool for q in checks)):
            errors.append('source.quote_checks needs excerpt text and boolean found')
    for item in project.get('evidence', []):
        if not isinstance(item, dict):
            continue
        if 'claim_scope' in item and item['claim_scope'] not in tuple(SCOPES):
            errors.append(f"{item.get('evidence_id')}: invalid claim_scope")
        if 'support' not in item:
            continue
        support = item['support']
        if not isinstance(support, list):
            errors.append('evidence.support must be an array')
            continue
        for link in support:
            if not isinstance(link, dict) or not all(text(link.get(k)) for k in ('source_id', 'locator', 'reason')):
                errors.append('support needs source_id, locator, reason')
            elif link['source_id'] not in source_ids or link['source_id'] not in item.get('source_ids', []):
                errors.append('support must reference a source registered on the evidence')
            if isinstance(link, dict) and link.get('relation') not in ('supports', 'context', 'contradicts'):
                errors.append('support.relation must be supports/context/contradicts')
            if isinstance(link, dict) and 'passage' in link and not text(link['passage']):
                errors.append('support.passage must be nonempty text')
    design = project.get('validation_design')
    if design is not None:
        if not isinstance(design, dict):
            errors.append('validation_design must be an object')
        else:
            if design.get('status') not in ('planned', 'running', 'completed'):
                errors.append('validation_design.status must be planned/running/completed')
            if design.get('purpose') not in ('quality', 'demand', 'causal_effect', 'exploratory'):
                errors.append('validation_design.purpose is unknown')
            if design.get('data_origin') not in ('none', 'synthetic', 'real'):
                errors.append('validation_design.data_origin must be none/synthetic/real')
            sample = design.get('sample')
            if not isinstance(sample, dict) or any(type(sample.get(k)) is not int or sample[k] < 1 for k in ('cases', 'variants', 'repeats', 'planned_outputs')):
                errors.append('validation_design.sample needs positive cases/variants/repeats/planned_outputs')
            thresholds = design.get('thresholds')
            if not isinstance(thresholds, list):
                errors.append('validation_design.thresholds must be an array')
            else:
                for threshold in thresholds:
                    if not isinstance(threshold, dict) or not all(text(threshold.get(k)) for k in ('metric', 'value', 'rationale')):
                        errors.append('threshold needs metric, value, rationale')
                        continue
                    if threshold.get('basis') not in ('proposed', 'owner_agreed', 'empirical'):
                        errors.append('threshold.basis must be proposed/owner_agreed/empirical')
                    if threshold.get('basis') == 'owner_agreed' and not text(threshold.get('agreement_reference')):
                        errors.append('owner_agreed threshold needs an agreement_reference to the actual user decision')
                    if threshold.get('basis') == 'empirical':
                        refs = threshold.get('evidence_ids')
                        if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in evidence_ids for r in refs):
                            errors.append('empirical threshold needs registered evidence_ids')
            if 'results' in design and not isinstance(design['results'], dict):
                errors.append('validation_design.results must be an object')
            elif isinstance(design.get('results'), dict):
                results = design['results']
                if 'source_ids' in results and (not isinstance(results['source_ids'], list) or
                        any(not isinstance(s, str) or s not in source_ids for s in results['source_ids'])):
                    errors.append('results.source_ids must reference registered sources')
                for field in ('artifact_path', 'summary'):
                    if field in results and not text(results[field]):
                        errors.append('results.' + field + ' must be nonempty text')
    review = project.get('strategy_review')
    if review is not None and (not isinstance(review, dict) or
            not all(text(review.get(k)) for k in (*REVIEW_FIELDS, 'state_hash', 'reviewer'))):
        errors.append('strategy_review needs comparison, objection, reversal condition, evidence limits, state_hash and reviewer')
    return errors


def assess(project, path, root):
    blockers = []
    notes = []
    if not project.get('research_requirements'):
        blockers.append('Define research_requirements: which source kinds this task needs, and why')
    sources = {s['source_id']: s for s in project['sources']}
    base = path.parent if project.get('path_base') == 'project' else root
    active_evidence = [e for e in project['evidence'] if e['status'] not in ('withdrawn', 'stale', 'contradicted')]
    for item in active_evidence:
        if item['claim_type'] not in FACTS:
            continue
        eid = item['evidence_id']
        links = item.get('support', [])
        supporting = [link for link in links if link['relation'] == 'supports']
        if not item.get('claim_scope') or not supporting:
            blockers.append(f'{eid}: record claim_scope and explicit supporting passage/reason; a URL alone is insufficient')
        if any(link['relation'] == 'contradicts' for link in links):
            blockers.append(f'{eid}: unresolved contradictory source; downgrade or resolve the claim')
        for link in supporting:
            source = sources[link['source_id']]
            passage = link.get('passage')
            quote_checks = source.get('quote_checks') or []
            if passage and quote_checks and not any(q['found'] and
                    re.sub(r'\s+', ' ', passage).strip() in re.sub(r'\s+', ' ', q['excerpt']).strip()
                    for q in quote_checks):
                blockers.append(f'{eid}: supporting passage is not one of the quotations actually found in the input')
            location = source.get('snapshot_path') or source['url_or_path']
            candidate = (base / location).resolve() if not location.startswith(('https://', 'http://')) else None
            if not passage:
                blockers.append(f'{eid}: preserve the supporting passage, not only a URL or page number')
            elif candidate is None or not candidate.is_relative_to(base.resolve()) or not candidate.is_file():
                blockers.append(f'{eid}: supporting passage has no accessible registered local source')
            else:
                try:
                    original = candidate.read_text(encoding='utf-8-sig')
                    if re.sub(r'\s+', ' ', passage).strip() not in re.sub(r'\s+', ' ', original):
                        blockers.append(f'{eid}: supporting passage does not match the saved source')
                except (OSError, UnicodeError):
                    blockers.append(f'{eid}: supporting passage could not be checked as UTF-8 text')
            if source.get('kind') in ('model_respondent', 'agent_note'):
                blockers.append(f'{eid}: model-generated content cannot substantiate a fact')
            if item.get('claim_scope') in ('market_demand', 'causal_effect', 'project_observation'):
                if source.get('synthetic') or source['kind'] == 'synthetic':
                    blockers.append(f'{eid}: synthetic material cannot establish a real-world effect or demand')
                if item['claim_scope'] == 'market_demand' and source.get('evidence_scope') != 'market_observation':
                    blockers.append(f'{eid}: general guidance or a source description is not market-demand evidence')
                if item['claim_scope'] == 'causal_effect':
                    design = project.get('validation_design', {})
                    if not (design.get('purpose') == 'causal_effect' and design.get('status') == 'completed'
                            and design.get('data_origin') == 'real'):
                        blockers.append(f'{eid}: causal effect requires an executed real-data design; a plan is insufficient')
            if source.get('content_kind') == 'summary':
                blockers.append(f'{eid}: a source summary is context; inspect the supporting original passage')
            elif source['kind'] == 'website' and source.get('content_kind') not in ('page', 'excerpt'):
                blockers.append(f'{eid}: record whether the web capture is an original page, excerpt or summary')
            if source.get('quote_checks') and not any(q.get('found') for q in source['quote_checks']):
                blockers.append(f'{eid}: requested quotations were not found in the supplied text')
    design = project.get('validation_design')
    if not design:
        blockers.append('Record validation_design separately from the narrative plan')
        experiment_status = 'not_recorded'
    else:
        experiment_status = design['status']
        sample = design['sample']
        expected = sample['cases'] * sample['variants'] * sample['repeats']
        if sample['planned_outputs'] != expected:
            blockers.append(f'Planned output count mismatch: {sample["cases"]} × {sample["variants"]} × {sample["repeats"]} = {expected}')
        if not design['thresholds'] and not text(design.get('thresholds_rationale')):
            blockers.append('Explain why this exploratory design has no numerical thresholds')
        for threshold in design['thresholds']:
            if threshold['basis'] == 'proposed':
                notes.append(f'Proposed threshold, not owner-approved or a result: {threshold["metric"]} = {threshold["value"]}')
            if threshold['basis'] == 'empirical':
                by_id = {e['evidence_id']: e for e in project['evidence']}
                for eid in threshold['evidence_ids']:
                    basis = by_id[eid]
                    if basis['claim_type'] not in ('measured_fact', 'qualitative_signal') or basis['status'] != 'corroborated':
                        blockers.append(f'Empirical threshold needs corroborated observation, not {eid}')
                    if any(sources[sid].get('synthetic') or sources[sid]['kind'] in ('synthetic', 'model_respondent', 'agent_note') for sid in basis['source_ids']):
                        blockers.append(f'Empirical threshold cannot rely on synthetic/model evidence {eid}')
        for field in ('unit_of_analysis', 'comparison', 'stop_rule', 'inference_limits'):
            if not text(design.get(field)):
                blockers.append('Missing validation_design.' + field)
        if design['purpose'] == 'causal_effect' and not text(design.get('assignment')):
            blockers.append('Causal-effect design needs assignment/randomization and its assumptions')
        if design['status'] == 'completed':
            results = design.get('results', {})
            location = results.get('artifact_path')
            candidate = (base / location).resolve() if isinstance(location, str) else None
            if candidate is None or not candidate.is_relative_to(base.resolve()) or not candidate.is_file():
                blockers.append('Completed experiment needs an existing local results artifact inside the workspace')
            refs = results.get('source_ids', [])
            if not refs or any(s not in sources for s in refs):
                blockers.append('Completed experiment needs registered result sources')
            elif candidate is not None:
                registered_paths = set()
                for sid in refs:
                    for key in ('url_or_path', 'snapshot_path'):
                        value = sources[sid].get(key)
                        if value and not value.startswith(('https://', 'http://')):
                            registered_paths.add((base / value).resolve())
                if candidate not in registered_paths:
                    blockers.append('Results artifact must be one of the registered result-source files, not an unrelated report')
            if not text(results.get('summary')):
                blockers.append('Completed experiment needs an observed-results summary')
            if design['data_origin'] == 'none':
                blockers.append('Completed experiment cannot have data_origin=none')
        else:
            notes.append('Experiment has not been completed; do not report its plan or thresholds as observed results')
    review = project.get('strategy_review')
    if not review:
        blockers.append('Record strategy_review: common comparison criteria, strongest objection, reversal condition and limits')
    elif review['state_hash'] != state_hash(project, path, root):
        blockers.append('Strategy review is stale: task, sources, evidence, strategy or experiment design changed')
    return {'status': 'review_record_complete' if not blockers else 'needs_review',
            'blockers': blockers, 'notes': notes, 'experiment_status': experiment_status,
            'state_hash': state_hash(project, path, root),
            'independent_truth_check': False,
            'note': 'Checks explicit records and consistency. A self-review is not independent verification of claim meaning or strategy quality.'}
