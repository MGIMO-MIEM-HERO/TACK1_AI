#!/usr/bin/env python3
"""Render the README argument map from a public, fictional teaching snapshot.

Captions are editorial summaries, not generated private reasoning.
Run with --check to verify SVG freshness and its case references (stdlib only).
"""
import argparse
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / 'examples/paired-case-review/project.json'
OUT = ROOT / 'docs/assets/agent-analysis-map.svg'
GREEN, PURPLE = '#008c46', '#731982'


def build():
    case = json.loads(CASE.read_text(encoding='utf-8'))
    evidence = {e['evidence_id']: e for e in case['evidence']}
    # Fail if the saved snapshot no longer supports these editorial captions.
    assert case['recommended_option_id'] == 'O2' and case['chosen_option_id'] == 'O1'
    assert all(evidence[e]['status'] == 'stale' for e in ('E4', 'H2'))
    assert evidence['H1']['claim_type'] == 'hypothesis'
    assert all(evidence[e]['source_ids'] == ['POLICY'] for e in ('E9', 'E10', 'E11'))
    assert all(evidence[e]['status'] != 'stale' for e in ('E9', 'E10', 'E11'))
    assert {'O0', 'O1', 'O2', 'O3'} == {o['option_id'] for o in case['options']}
    assert evidence['E7']['source_ids'] == ['BRIEF']
    assert 'Q1' in {q['question_id'] for q in case['research_questions']}
    svg = ['<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 1780" width="780" height="1780" role="img" aria-labelledby="title desc" lang="ru">',
        '<title id="title">Как агент обосновывает рекомендацию</title>',
        '<desc id="desc">Вымышленный учебный снимок paired-case-review. POLICY v2 поддерживает E9 и E10: ресурс разработчика отозван, бумажная подготовка допустима без кода. E4 и H2 устарели; неизвестные часы команды и гипотеза H1 не становятся фактами. Сравнение O0, O1, O2 и O3 приводит к записанной рекомендации O2; прежний выбор владельца O1 сохранён. При новых данных варианты сравниваются заново. Это карта сохранённых оснований и кратких объяснений, не скрытые рассуждения модели.</desc>',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="10" markerHeight="10" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M1 1 L9 5 L1 9" fill="none" stroke="#008c46" stroke-width="2"/></marker></defs>',
        '<rect width="780" height="1780" rx="28" fill="#f5f7f6"/>',
        '<g font-family="Segoe UI, Arial, sans-serif">']

    def text(x, y, value, size=28, color='#334b3d', weight=400, anchor='start'):
        svg.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>')

    def card(identity, x, y, w, h, title, body, fill='#fff', border='#d2e2d8', color=GREEN, size=28):
        svg.append(f'<g id="{identity}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="22" fill="{fill}" stroke="{border}" stroke-width="2"/>')
        text(x+22, y+43, title, size, color, 700)
        for i, line in enumerate(body):
            text(x+22, y+85+36*i, line, 27, '#fff' if fill == PURPLE else '#334b3d')
        svg.append('</g>')

    def link(source, target, path, dashed=False):
        dash = ' stroke-dasharray="7 6"' if dashed else ''
        svg.append(f'<path data-from="{source}" data-to="{target}" d="{path}" fill="none" stroke="{PURPLE if dashed else GREEN}" stroke-width="2.5"{dash} marker-end="url(#arrow)"/>')

    text(36, 48, 'ВЫМЫШЛЕННЫЙ УЧЕБНЫЙ СНИМОК', 21, GREEN, 700)
    text(36, 94, 'Как обоснована рекомендация', 34, '#23282b', 700)
    # Links are laid out before cards; no link passes through a text label.
    link('question', 'resource', 'M300 270 V304 H200 V344')
    link('question', 'paper', 'M480 270 V304 H580 V344')
    link('resource', 'stale', 'M200 530 V608')
    link('paper', 'unknown', 'M580 530 V608', True)
    link('resource', 'comparison', 'M36 437 H24 Q18 437 18 445 V904 Q18 912 26 912 H36')
    link('paper', 'comparison', 'M744 437 H754 Q762 437 762 445 V904 Q762 912 754 912 H744')
    link('comparison', 'recommendation', 'M200 1132 V1208')
    link('recommendation', 'owner', 'M364 1298 H416')
    link('recommendation', 'revisit', 'M200 1388 V1460', True)
    text(200, 575, 'отзывает основание', 23, PURPLE, anchor='middle')
    text(580, 575, 'не доказывает эффект', 22, PURPLE, anchor='middle')
    text(200, 1177, 'обоснование', 23, PURPLE, anchor='middle')
    text(580, 1177, 'запрос решения', 23, PURPLE, anchor='middle')
    text(390, 1433, 'новые данные → повторное сравнение', 23, PURPLE, anchor='middle')
    card('question', 126, 140, 528, 130, 'Агент и вопрос решения · Q1',
         ['Что выполнимо к сроку кейса?'], fill='#e6f6ed', border='#00ab55', size=30)
    card('resource', 36, 344, 328, 186, 'POLICY v2 → E9',
         ['Нет разработчика', 'и замены к сроку'])
    card('paper', 416, 344, 328, 186, 'POLICY v2 → E10',
         ['Бумажный план', 'допустим без кода'])
    card('stale', 36, 608, 328, 174, 'E4 / H2 · устарело',
         ['Прежнее условие v1', 'больше не основание'], fill='#f4eaf6', border='#d6b8dc', color=PURPLE)
    card('unknown', 416, 608, 328, 174, 'Что ещё неизвестно',
         ['Часы команды · эффект', 'H1: гипотеза, не спрос'], fill='#f4eaf6', border='#d6b8dc', color=PURPLE, size=27)
    text(36, 829, 'E11: задержка интеграции ≠ потеря разработчика.', 26)
    card('comparison', 36, 864, 708, 268, 'Сравнение альтернатив по основаниям',
         ['O0 · ручной чек-лист — если нет ресурса на O2',
          'O1 · прототип — нет разработчика к сроку',
          'O2 · бумага — без кода; часы ещё уточнить',
          'O3 · заморозить — если обучение не нужно',
          'Бумага не проверяет реализацию и спрос.'], size=29)
    card('recommendation', 36, 1208, 328, 180, 'Рекомендация: O2',
         ['E9 + E10: начать', 'с бумажного сценария'], fill='#f4eaf6', border='#d6b8dc', color=PURPLE, size=27)
    card('owner', 416, 1208, 328, 180, 'Выбор владельца: O1',
         ['Не заменён агентом', 'Ждёт ответа владельца'], fill=PURPLE, border=PURPLE, color='#fff', size=25)
    card('revisit', 36, 1460, 708, 170, 'Что может изменить рекомендацию?',
         ['Появится ресурс на O1 → сравнить заново.',
          'Нет ресурса на O2 → рассмотреть O0.'], size=29)
    text(36, 1679, 'Неизвестное ≠ факт и не доказанная невозможность.', 25)
    text(36, 1718, 'Основания и краткие объяснения из сохранённых записей.', 24)
    text(36, 1754, 'Не скрытые рассуждения модели и не доказательство спроса.', 23)
    svg.append('</g></svg>')
    return '\n'.join(svg)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    output = build()
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding='utf-8') != output:
            parser.exit(1, 'Argument map differs; run the generator.\n')
        print('Argument map and case references: OK')
    else:
        OUT.write_text(output, encoding='utf-8')
        print(OUT)


if __name__ == '__main__':
    main()
