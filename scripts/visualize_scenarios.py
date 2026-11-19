"""Saved scenario views; no simulation, state mutation, or automatic decisions."""


def scenario_views(project, audit, data):
    from stress_test import comparison_context
    versions = project.get('decision_stress_tests', [])
    ids = {n['id'] for n in data['nodes']}
    options = {row['option_id']: row for row in project['options']}
    checked = audit.get('decision_stress_test', {})
    result = []
    for index, review in enumerate(versions):
        latest = index == len(versions) - 1
        status = checked.get('status', 'not_checked') if latest else 'historical'
        comparable = latest and status == 'review_record_complete'
        evaluated = {row['scenario_id']: row for row in checked.get('scenarios', [])} if comparable else {}
        root = 'stress:' + review['review_id']
        assumptions = {row['assumption_id']: row for row in review['assumptions']}
        scenarios = []
        for scenario in review['scenarios']:
            key = root + ':scenarios:' + scenario['scenario_id']
            keys = {root, key}
            eids = set(scenario['evidence_ids']) | set(scenario['changed_evidence_ids'])
            eids.update(scenario['recommendation']['evidence_ids'])
            for aid in scenario['assumption_ids']:
                keys.add(root + ':assumptions:' + aid)
                eids.update(assumptions[aid]['evidence_ids'])
            rows = []
            for row in scenario['option_impacts']:
                oid = row['option_id']
                eids.update(row['evidence_ids'])
                rows.append({**row, 'title': options[oid]['title'] if comparable and oid in options else oid,
                             'node_id': 'o:' + oid if comparable and 'o:' + oid in ids else None})
            if comparable:
                keys.update('o:' + row['option_id'] for row in rows)
                keys.update('e:' + eid for eid in eids)
                sids = set(scenario['changed_source_ids'])
                for row in project['evidence']:
                    if row['evidence_id'] in eids:
                        sids.update(row['source_ids'])
                keys.update('s:' + sid for sid in sids)
            keys.intersection_update(ids)
            edge_indexes = [i for i, edge in enumerate(data['edges'])
                            if edge['source'] in keys and edge['target'] in keys]
            scenarios.append({'scenario_id': scenario['scenario_id'], 'title': scenario['title'],
                              'node_id': key, 'premise': scenario['premise'],
                              'premise_status': scenario['premise_status'],
                              'constraint_changes': scenario['constraint_changes'],
                              'changed_source_ids': scenario['changed_source_ids'],
                              'changed_evidence_ids': scenario['changed_evidence_ids'],
                              'assumptions': [assumptions[aid] for aid in scenario['assumption_ids']],
                              'option_impacts': rows, 'conditional_recommendation': scenario['recommendation'],
                              'new_data_needed': scenario['new_data_needed'], 'review_trigger': scenario['review_trigger'],
                              'evaluation': evaluated.get(scenario['scenario_id']),
                              'nodes': sorted(keys), 'edge_indexes': edge_indexes})
        result.append({'review_id': review['review_id'], 'status': status,
                       'recorded_at': review.get('recorded_at'), 'graph_comparable': comparable,
                       'comparison': comparison_context(review), 'limitations': review['limitations'],
                       'blockers': checked.get('blockers', []) if latest else [], 'scenarios': scenarios,
                       'actual_recommendation': project.get('recommended_option_id'),
                       'actual_human_choice': project.get('chosen_option_id'),
                       'note': 'Это просмотр сохранённого условного разбора, не новый расчёт и не прогноз. '
                               'Сценарий не применён к решению; рекомендация, выбор, ресурсы, сроки и ответы владельца не меняются.'})
    return result
