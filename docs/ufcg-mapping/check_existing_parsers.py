"""Read local UFCG captures through existing parsers; print counts, never student data.

This is a compatibility probe, not a declaration of live integration support.
Run from repository root: .venv/bin/python -m docs.ufcg-mapping.check_existing_parsers
"""
from dataclasses import asdict
from pathlib import Path

from bs4 import BeautifulSoup

from sigaa.parsers.attendance import parse_attendance
from sigaa.parsers.grades import parse_grades, parse_turma_grades
from sigaa.parsers.matricula_extraordinaria import parse_classes
from sigaa.parsers.news import parse_news_body, parse_news_list
from sigaa.parsers.participantes import parse_professors
from sigaa.parsers.plano import parse_course_plan
from sigaa.parsers.portal import parse_student, parse_turmas

ROOT = Path(__file__).resolve().parents[2] / 'captures/sigaa-ufcg/2026-09-18'


def html(stem):
    text = (ROOT / (stem + '.html')).read_text()
    if not text.rstrip().endswith('</html>'):
        raise ValueError(f'Incomplete capture: {stem}; recapture before probing')
    return text


if __name__ == '__main__':
    student = parse_student(html('auth-039-portal-completo'))
    print('student_fields_present', {k: bool(v) for k, v in asdict(student).items()})
    turmas = parse_turmas(html('auth-039-portal-completo'))
    print('turmas', len(turmas), 'schedule_present', sum(bool(t.schedule_raw) for t in turmas),
          'room_looks_like_schedule', sum(bool(t.room and '(' in t.room) for t in turmas))
    grades = html('auth-017-notas-gerais')
    print('grades', len(parse_grades(grades)), 'table_rows',
          sum(len(t.select('tbody tr')) for t in BeautifulSoup(grades, 'lxml').select('table.tabelaRelatorio')))
    plan = parse_course_plan(html('auth-003-plano'), 'sample')
    assert plan is not None and plan.schedule and plan.evaluations
    print('plan', len(plan.schedule), len(plan.evaluations))
    for capture_id in ['auth-006-frequencia', 'auth-023-frequencia-anterior']:
        attendance = parse_attendance(html(capture_id), 'sample')
        print(capture_id, len(attendance.records),
              {k: v is not None for k, v in asdict(attendance).items() if k not in ['id_turma', 'records']})
    print('professors', len(parse_professors(html('auth-016-participantes'), 'sample')))
    print('news', len(parse_news_list(html('auth-002-turma-principal'), 'sample')))
    print('news_body_has_navigation', 'Menu Turma Virtual' in parse_news_body(html('auth-005-noticia-detalhe')))
    grade = parse_turma_grades(html('auth-022-notas-preenchidas'), 'sample')
    print('turma_grade_fields_present', {k: bool(v) for k, v in asdict(grade).items()})
    print('extraordinary_classes',
          len(parse_classes(html('auth-072-extraordinaria-ofertas-completo'))))
