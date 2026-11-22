#!/usr/bin/env python3
"""Build the README process map (stdlib only, no project/user data).

Run: python scripts/build_agent_work_graph.py
Verify committed SVG: python scripts/build_agent_work_graph.py --check
The editable source is this file. GitHub displays the output without JavaScript.
"""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs/assets/agent-work-graph.svg'
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
GREEN, PURPLE = '#008c46', '#731982'


def build():
    def element(parent, tag, **attrs):
        return ET.SubElement(parent, f'{{{NS}}}{tag}', {k.replace('_', '-'): str(v) for k, v in attrs.items()})

    svg = ET.Element(f'{{{NS}}}svg', {'viewBox': '0 0 780 1490', 'width': '780', 'height': '1490',
        'role': 'img', 'aria-labelledby': 'map-title map-desc', 'lang': 'ru'})
    element(svg, 'title', id='map-title').text = 'Карта работы агента «Контур решения»'
    element(svg, 'desc', id='map-desc').text = (
        'Агент и задача: цель и ограничения. Материалы ведут к фактам, гипотезам и неизвестному, '
        'связанным с источниками. Затем альтернативы, проверки ресурсов и осуществимости, '
        'неблагоприятных сценариев и существенных обещаний, рекомендация агента и отдельное '
        'решение владельца. Новые данные и изменения оснований возвращают к пересмотру. '
        'Неизвестное требует уточнения и не означает невозможности. '
        'Это схема процесса и записанных оснований, не скрытые рассуждения и не доказательство истинности.')
    defs = element(svg, 'defs')
    for name, color in [('flow-arrow', GREEN), ('review-arrow', PURPLE)]:
        marker = element(defs, 'marker', id=name, viewBox='0 0 10 10', refX=9, refY=5,
                         markerWidth=10, markerHeight=10, orient='auto-start-reverse', markerUnits='userSpaceOnUse')
        element(marker, 'path', d='M1 1 L9 5 L1 9', fill='none', stroke=color,
                stroke_width=2, stroke_linecap='round', stroke_linejoin='round')
    element(svg, 'rect', width=780, height=1490, rx=28, fill='#f5f7f6')
    content = element(svg, 'g', font_family='Segoe UI, Arial, sans-serif')

    def text(parent, x, y, value, size=26, color='#334b3d', weight=400, **attrs):
        node = element(parent, 'text', x=x, y=y, font_size=size, fill=color, font_weight=weight, **attrs)
        node.text = value
        return node

    text(content, 36, 53, 'КОНТУР РЕШЕНИЯ', 22, GREEN, 700, letter_spacing=2)
    text(content, 36, 99, 'Основания → выбор → пересмотр', 34, '#23282b', 700)
    links = element(content, 'g', fill='none', stroke=GREEN, stroke_width=2.5,
                    stroke_linecap='round', stroke_linejoin='round', id='process-links')
    paths = [
        ('task', 'materials', 'M390 396 V374 Q390 366 382 366 H208 Q200 366 200 358 V340'),
        ('materials', 'evidence', 'M364 238 H416'),
        ('evidence', 'options', 'M580 340 V592'),
        ('options', 'checks', 'M580 772 V844'),
        ('checks', 'recommendation', 'M580 1084 V1156'),
        ('recommendation', 'owner', 'M416 1246 H364'),
        ('owner', 'changes', 'M36 1246 H26 Q18 1246 18 1238 V690 Q18 682 26 682 H36'),
    ]
    for source, target, path in paths:
        element(links, 'path', d=path, marker_end='url(#flow-arrow)', data_from=source, data_to=target)
    element(links, 'path', d='M56 592 V340', stroke=PURPLE, stroke_dasharray='7 7',
            marker_end='url(#review-arrow)', data_from='changes', data_to='materials')
    text(content, 214, 463, 'Пересмотр', 24, PURPLE, 600, text_anchor='end')
    text(content, 214, 495, 'оснований', 24, PURPLE, text_anchor='end')

    def card(identity, x, y, w, h, title, body, fill='#fff', border='#d2e2d8',
             title_color=GREEN, body_color='#334b3d', title_size=30):
        group = element(content, 'g', id=identity)
        element(group, 'rect', x=x, y=y, width=w, height=h, rx=24, fill=fill, stroke=border, stroke_width=2)
        text(group, x+22, y+47, title, title_size, title_color, 700)
        for index, line in enumerate(body):
            text(group, x+22, y+89+index*36, line, 28, body_color)
        return group

    card('materials', 36, 136, 328, 204, '1 Материалы',
         ['Документы и данные', 'Ссылки и фрагменты', 'Проверка источников'])
    card('evidence', 416, 136, 328, 204, '2 Основания',
         ['Факты и гипотезы', 'Неизвестное отдельно', 'Вывод ↔ источник'])
    task = element(content, 'g', id='task')
    element(task, 'rect', x=228, y=396, width=324, height=140, rx=54, fill='#00ab55')
    text(task, 390, 452, 'Агент и задача', 32, '#fff', 700, text_anchor='middle')
    text(task, 390, 494, 'Цель · ограничения', 28, '#fff', text_anchor='middle')
    card('changes', 36, 592, 328, 180, '7 Новые данные',
         ['Источники изменены', 'Пересмотр выводов'], fill='#f4eaf6', border='#d6b8dc', title_color=PURPLE)
    card('options', 416, 592, 328, 180, '3 Альтернативы',
         ['Включая «не менять»', 'и «остановить»'])
    checks = card('checks', 36, 844, 708, 240, '4 Проверки', [])
    for y, label in [(937, 'Ресурсы и осуществимость'), (980, 'Неблагоприятные сценарии'),
                     (1023, 'Существенные обещания')]:
        element(checks, 'circle', cx=65, cy=y-8, r=4, fill=GREEN)
        text(checks, 84, y, label, 28)
    card('recommendation', 416, 1156, 328, 180, '5 Рекомендация',
         ['Обоснование и риски', 'Условия пересмотра'], fill='#f4eaf6', border='#d6b8dc', title_color=PURPLE)
    card('owner', 36, 1156, 328, 180, '6 Решение человека',
         ['Явный ответ', 'на версию решения'], fill=PURPLE, border=PURPLE,
         title_color='#fff', body_color='#fff', title_size=27)
    text(content, 36, 1390, 'Неизвестное требует уточнения, а не отказа.', 26, '#334b3d')
    text(content, 36, 1430, 'Стрелки — процесс. Пунктир — возврат к пересмотру.', 24, '#52645a')
    text(content, 36, 1465, 'Карта записанных оснований, не скрытых рассуждений.', 24, '#52645a')
    ET.indent(svg, space='  ')
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(svg, encoding='unicode') + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='check the committed SVG without writing')
    args = parser.parse_args()
    output = build()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding='utf-8') != output:
            parser.exit(1, 'SVG differs from its editable source; run the generator.\n')
        print('SVG matches its source.')
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(output, encoding='utf-8')
        print(OUTPUT)


if __name__ == '__main__':
    main()
