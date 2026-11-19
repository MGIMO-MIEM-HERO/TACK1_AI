"""Paths over saved option dependencies, never a causal or confidence model."""


def decision_paths(project, audit, data):
    evidence = {row['evidence_id']: row for row in project['evidence']}
    node_ids = {n['id'] for n in data['nodes']}
    result = []
    for option in project['options']:
        oid = option['option_id']
        selected = 'o:' + oid
        stress = project.get('decision_stress_tests', [])
        assumption_rows = [row for row in stress[-1]['assumptions'] if oid in row['option_ids']] if stress else []
        pending = list(option['evidence_ids'])
        pending.extend(eid for row in assumption_rows for eid in row['evidence_ids'])
        seen, eids, sids, missing = set(), [], [], []
        while pending:
            eid = pending.pop(0)
            if eid in seen:
                continue
            seen.add(eid)
            row = evidence.get(eid)
            if row is None:
                missing.append(eid)
                continue
            eids.append(eid)
            sids.extend(sid for sid in row['source_ids'] if sid not in sids)
            pending.extend(row.get('related_evidence_ids', []))
        grounds = ['e:' + eid for eid in eids]
        sources = ['s:' + sid for sid in sids if 's:' + sid in node_ids]
        pairs, support, contradictions = set(), [], []
        for eid in eids:
            row = evidence[eid]
            for sid in row['source_ids']:
                pairs.add(('s:' + sid, 'e:' + eid))
            for ref in row.get('related_evidence_ids', []):
                if ref in seen:
                    pairs.add(('e:' + ref, 'e:' + eid))
            for link in row.get('support', []):
                support.append({'evidence_id': eid, **link})
                if link['relation'] == 'contradicts':
                    contradictions.append(['s:' + link['source_id'], 'e:' + eid])
        pairs.update(('e:' + eid, selected) for eid in option['evidence_ids'])
        assumptions, checks = [], ['review', 'next']
        if stress:
            review = stress[-1]
            for row in assumption_rows:
                key = 'stress:' + review['review_id'] + ':assumptions:' + row['assumption_id']
                if oid in row['option_ids'] and key in node_ids:
                    assumptions.append(key)
                    pairs.add((selected, key))
                    pairs.update(('e:' + eid, key) for eid in row['evidence_ids'] if eid in seen)
        plans = project.get('feasibility_reviews', [])
        if plans:
            key = 'feasibility:' + plans[-1]['review_id'] + ':' + oid
            if key in node_ids:
                checks.append(key)
                pairs.add((selected, key))
        research = project.get('research_selection_reviews', [])
        if research:
            for gap in research[-1]['gaps']:
                key = 'research:' + research[-1]['review_id'] + ':gaps:' + gap['question_id']
                if oid in gap['option_ids'] and key in node_ids:
                    checks.append(key)
                    pairs.add((selected, key))
        pairs.update(((selected, 'review'), ('review', 'next')))
        keys = set(sources + grounds + assumptions + [selected] + checks)
        # Only already-generated edges can be highlighted; navigation and history are excluded.
        edge_indexes = [i for i, edge in enumerate(data['edges'])
                        if (edge['source'], edge['target']) in pairs and
                        edge['source'] in keys and edge['target'] in keys]
        result.append({'option_id': oid, 'title': option['title'], 'node_id': selected,
                       'is_recommended': oid == project.get('recommended_option_id'),
                       'is_human_choice': oid == project.get('chosen_option_id'),
                       'sources': sources, 'evidence': grounds, 'assumptions': assumptions,
                       'checks': checks, 'nodes': sorted(keys), 'edge_indexes': edge_indexes,
                       'support': support, 'contradictions': contradictions,
                       'limitations': [dict(evidence_id=eid, claim_type=evidence[eid]['claim_type'],
                                            status=evidence[eid]['status'], text=evidence[eid]['limitations'])
                                       for eid in eids],
                       'review_statuses': {k: audit.get(k, {}).get('status', 'не проверено') for k in
                                           ('decision_stress_test', 'feasibility', 'research_selection')},
                       'missing_evidence_ids': missing,
                       'note': 'Показаны записанные источники, основания и связанные допущения/проверки. '
                               'Связи не доказывают причинность или истинность. Общая проверка и следующий '
                               'шаг не являются отдельным результатом этого варианта. Исторические версии не включены.'})
    return result
