from types import SimpleNamespace

from django.test import SimpleTestCase

from .models import QuestionType
from .services import grade


def q(pk, qtype, correct, all_ids, points=1):
    opts = [SimpleNamespace(pk=i, is_correct=i in correct) for i in all_ids]
    return SimpleNamespace(pk=pk, qtype=qtype, points=points, options=SimpleNamespace(all=lambda: opts))


class GradeTests(SimpleTestCase):
    def setUp(self):
        self.questions = [
            q(1, QuestionType.SINGLE_CHOICE, {11}, [10, 11, 12]),
            q(2, QuestionType.MULTI_SELECT, {20, 22}, [20, 21, 22], points=2),
            q(3, QuestionType.TRUE_FALSE, {30}, [30, 31]),
        ]

    def test_all_correct(self):
        r = grade(self.questions, {"1": ["11"], "2": ["20", "22"], "3": ["30"]})
        self.assertEqual((r["earned"], r["total"], r["score"]), (4, 4, 100.0))

    def test_partial_multi_select_gets_no_credit(self):
        r = grade(self.questions, {"1": ["11"], "2": ["20"], "3": ["31"]})
        self.assertEqual(r["earned"], 1)
        self.assertEqual(r["score"], 25.0)

    def test_foreign_and_multiple_answers_rejected(self):
        r = grade(self.questions, {"1": ["11", "12"], "2": ["999"], "3": []})
        self.assertEqual(r["earned"], 0)
