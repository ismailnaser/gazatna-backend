from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from assignments.models import QuestionType
from assignments.quiz_services import _score_question, recalculate_quiz_submission_score


class QuizScoringTests(SimpleTestCase):
    def test_matching_dict_ignores_whitespace(self):
        question = SimpleNamespace(
            question_type=QuestionType.MATCHING,
            pairs=[{"left": "A", "right": "1"}],
            points=2,
            correct_index=None,
        )
        self.assertEqual(_score_question(question, {" A ": " 1 "}), Decimal("2"))

    def test_manual_score_ignores_invalid_decimal(self):
        submission = SimpleNamespace(auto_score="3", manual_scores={"1": "abc"})
        question = SimpleNamespace(id=1, question_type=QuestionType.ESSAY)
        self.assertEqual(recalculate_quiz_submission_score(submission, [question]), Decimal("3"))
