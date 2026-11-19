#!/usr/bin/env python3
"""Read-only entry point: restore a case and show the decision required from its owner."""
import argparse
import json
from pathlib import Path

from checkpoint import ROOT, ledger_summary
from project_tool import audit, load


def restore(path, *, at=None):
    path = path.resolve()
    project = load(path)
    result = audit(project, path, ready=True)
    options = {item['option_id']: item['title'] for item in project['options']}
    recommended = project.get('recommended_option_id')
    chosen = project.get('chosen_option_id')
    from follow_up import inspect as inspect_follow_up
    follow_up = result['follow_up'] if at is None else inspect_follow_up(project, path, ROOT, at=at, health=result['health'])
    review_blocked = (result['decision_stress_test']['blockers'] or result['marketing_claims_audit']['blockers']
                      or result['marketing_claims_audit']['publication_blockers'] or result['research_selection']['blockers']
                      or result['feasibility']['blockers'] or result['feasibility']['decision_blockers'])
    priorities = {g['question_id']: g['priority'] for g in result['research_selection'].get('gaps', [])}
    unresolved_branches = [r for r in result['research_selection'].get('branch_resolutions', [])
                           if r['status'] == 'insufficient_data' and priorities.get(r['question_id']) != 'defer']
    from resume_summary import build
    ledger = ledger_summary(path)
    summary = build(project, path, ROOT, result, follow_up, ledger)
    return {
        'resume_summary': summary,
        'project': str(path), 'title': project['title'], 'stage': project['stage'],
        'constraints': project.get('constraints', []),
        'recommendation': {'id': recommended, 'title': options.get(recommended),
                           'rationale': project.get('recommendation_rationale', '')},
        'human_choice': chosen,
        'decision_question': ('Сначала требуется пересмотр оснований; выбор решения пока не фиксируется.'
                              if result['errors'] or review_blocked else
                              summary['owner']['text'] if summary['owner']['status'] == 'awaiting_decision' else
                              result['material_changes']['human_questions'][0]['action']
                              if result['material_changes']['human_questions'] else
                              'Сначала нужно уточнить условие решения: ' + unresolved_branches[0]['next_step']
                              if unresolved_branches else 'Подтверждаете ли вы рекомендацию или выбираете другую альтернативу?'
                              if recommended and not chosen else
                              'Нужен ли пересмотр выбранного решения?' if chosen else
                              'Какое решение требуется принять и какие материалы доступны?'),
        'next_action': project['next_action'],
        'open_questions': project.get('unresolved_questions', []),
        'audit': result, 'content_review': result['content_review'],
        'experiment_status': result['content_review']['experiment_status'], 'ledger': ledger,
        'decision_stress_test': result['decision_stress_test'],
        'marketing_claims_audit': result['marketing_claims_audit'],
        'research_selection': result['research_selection'],
        'follow_up': follow_up,
        'feasibility': result['feasibility'],
        'material_changes': result['material_changes'],
        'workflow_files': sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'workflows').glob('*.md')),
        'instruction': 'Прочитай AGENTS.md. При ошибках сначала пересмотри основания. '
                       'Названия workflow бери из workflow_files. Не фиксируй выбор за человека.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path, help='Exact project.json path; cases are never selected implicitly')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--details', action='store_true', help='Show the existing full human-readable report')
    parser.add_argument('--acknowledge-summary', metavar='VERSION', help='Explicitly record viewing this summary version, never approval')
    parser.add_argument('--reviewer')
    parser.add_argument('--note')
    parser.add_argument('--as-of', help='Explicit offset-aware replay clock; read-only')
    args = parser.parse_args()
    try:
        from follow_up import instant
        if args.acknowledge_summary:
            if args.as_of or args.details or args.json: raise ValueError('View receipts use the current clock and reject report flags')
            from resume_summary import acknowledge
            print(json.dumps(acknowledge(args.project, args.acknowledge_summary, args.reviewer, args.note), ensure_ascii=False, indent=2))
            return 0
        if args.reviewer or args.note: raise ValueError('Reviewer/note require --acknowledge-summary VERSION')
        state = restore(args.project, at=instant(args.as_of) if args.as_of else None)
        if args.json:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            from resume_summary import markdown
            print(markdown(state['resume_summary']))
        if args.details and not args.json:
            print(state['title'])
            print('Ограничения: ' + ('; '.join(state['constraints']) or 'ещё не заданы'))
            print('Рекомендация: ' + str(state['recommendation']['title'] or 'ещё не сформирована'))
            print(state['recommendation']['rationale'])
            print('Выбор человека: ' + str(state['human_choice'] or 'не зафиксирован'))
            print('Ранее записанный шаг (проверьте актуальность): ' + state['next_action'])
            print('Структурная готовность: ' + ('да' if state['audit']['ready'] else 'требуется проверка'))
            for message in state['audit']['errors'] + state['audit']['warnings']:
                print('- ' + message)
            print('Содержательная проверка: ' + state['content_review']['status'])
            print('Эксперимент: ' + state['experiment_status'])
            print('Осуществимость (отдельно от разрешения): ' + state['feasibility']['status'])
            for row in state['feasibility']['assessments']:
                print('- ' + row['option_id'] + ': ' + row['outcome'] + '; ' + row['next_check'])
            if state['decision_stress_test']['status'] != 'not_recorded':
                print('Проверка решения на прочность: ' + state['decision_stress_test']['status'])
            if state['marketing_claims_audit']['status'] != 'not_recorded':
                print('Проверка обещаний: ' + state['marketing_claims_audit']['status'])
            if state['research_selection']['status'] != 'not_recorded':
                print('Выбор исследования: ' + state['research_selection']['status'])
                if state['research_selection']['recommendation']:
                    print('Обоснование следующего исследования: ' + state['research_selection']['recommendation']['rationale'])
                for row in state['research_selection'].get('branch_resolutions', []):
                    print('Развилка ' + row['question_id'] + ': ' + row['status'] + '; ветка ' + str(row['branch_id']))
                    print('Следующий шаг по развилке: ' + row['next_step'])
            print(state['decision_question'])
            if state['follow_up']['human_questions'] or state['follow_up']['metric_results']:
                print('Сопровождение: просрочено ' + str(len(state['follow_up']['overdue_commitments'])) +
                      '; новых/изменённых результатов ' + str(len(state['follow_up']['new_results'])))
                for question in state['follow_up']['human_questions']:
                    print('- ' + question['object_ref'] + ': ' + question['reason'] + ' ' + question['action'])
        # A blocked audit is visible to both humans and automation; nothing is saved.
        return 0 if not state['audit']['errors'] else 1
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        parser.exit(1, f'Start: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
