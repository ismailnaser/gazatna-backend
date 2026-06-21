from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from assignments.models import AssignmentStatus, QuestionType


def quiz_window_end(quiz, now=None):
    """Deadline for quiz availability (submission window), not per-attempt duration."""
    if quiz.end_at:
        return quiz.end_at
    if quiz.start_at and quiz.duration_minutes:
        return quiz.start_at + timedelta(minutes=quiz.duration_minutes)
    return None


def quiz_is_open(quiz, now=None):
    if quiz.status == AssignmentStatus.CLOSED:
        return False
    now = now or timezone.now()
    if quiz.start_at and now < quiz.start_at:
        return False
    end = quiz_window_end(quiz, now)
    if end and now > end:
        return False
    return True


def quiz_window_status(quiz, now=None):
    if quiz.status == AssignmentStatus.CLOSED:
        return "closed"
    now = now or timezone.now()
    if quiz.start_at and now < quiz.start_at:
        return "scheduled"
    end = quiz_window_end(quiz, now)
    if end and now > end:
        return "ended"
    return "active"


def quiz_max_score(questions):
    total = Decimal("0")
    for question in questions:
        total += Decimal(str(question.points or 1))
    return total


def _answer_for_question(question, answers, index):
    if isinstance(answers, dict):
        key = str(question.id)
        if key in answers:
            return answers[key]
        if question.id in answers:
            return answers[question.id]
    if isinstance(answers, list) and index < len(answers):
        return answers[index]
    return None


def _normalize_text(value):
    return str(value or "").strip().casefold()


def _score_question(question, answer):
    if answer is None:
        return Decimal("0")

    points = Decimal(str(question.points or 1))
    qtype = question.question_type or QuestionType.CHOICE

    if qtype in (QuestionType.CHOICE, QuestionType.TRUE_FALSE):
        if question.correct_index is None:
            return Decimal("0")
        try:
            return points if int(answer) == int(question.correct_index) else Decimal("0")
        except (TypeError, ValueError):
            return Decimal("0")

    if qtype == QuestionType.TERM:
        return Decimal("0")

    if qtype == QuestionType.ESSAY:
        return Decimal("0")

    if qtype == QuestionType.MATCHING:
        pairs = question.pairs or []
        if not pairs:
            return Decimal("0")
        if isinstance(answer, dict):
            correct = {(p.get("left"), p.get("right")) for p in pairs}
            student = {(left, right) for left, right in answer.items()}
            return points if student == correct else Decimal("0")
        if isinstance(answer, list):
            correct = {
                (_normalize_text(p.get("left")), _normalize_text(p.get("right")))
                for p in pairs
            }
            student = set()
            for item in answer:
                if isinstance(item, dict):
                    student.add(
                        (_normalize_text(item.get("left")), _normalize_text(item.get("right")))
                    )
            return points if student == correct else Decimal("0")
        return Decimal("0")

    if question.correct_index is not None:
        try:
            return points if int(answer) == int(question.correct_index) else Decimal("0")
        except (TypeError, ValueError):
            pass
    return Decimal("0")


def score_quiz_answers(questions, answers):
    total = Decimal("0")
    for index, question in enumerate(questions):
        answer = _answer_for_question(question, answers, index)
        total += _score_question(question, answer)
    return total


MANUAL_QUESTION_TYPES = (QuestionType.TERM, QuestionType.ESSAY)


def quiz_has_manual_questions(questions):
    return any((q.question_type or QuestionType.CHOICE) in MANUAL_QUESTION_TYPES for q in questions)


def recalculate_quiz_submission_score(submission, questions):
    auto = Decimal(str(submission.auto_score or 0))
    manual = Decimal("0")
    scores = submission.manual_scores or {}
    for question in questions:
        if (question.question_type or QuestionType.CHOICE) not in MANUAL_QUESTION_TYPES:
            continue
        raw = scores.get(str(question.id), scores.get(question.id))
        if raw is not None and raw != "":
            manual += Decimal(str(raw))
    return auto + manual


def quiz_max_attempts(quiz):
    return max(1, int(quiz.max_attempts or 1))


def quiz_attempt_count(quiz, student):
    from assignments.models import QuizSubmission

    return QuizSubmission.objects.filter(quiz=quiz, student=student).count()


def quiz_attempts_remaining(quiz, student):
    return max(0, quiz_max_attempts(quiz) - quiz_attempt_count(quiz, student))


def can_take_quiz_attempt(quiz, student, now=None):
    if not quiz_is_open(quiz, now):
        return False
    return quiz_attempts_remaining(quiz, student) > 0


def best_quiz_submission(quiz, student):
    from assignments.models import QuizSubmission

    return (
        QuizSubmission.objects.filter(quiz=quiz, student=student)
        .order_by("-score", "-attempt_number")
        .first()
    )


def best_quiz_submission_ids(submissions):
    best = {}
    for submission in submissions:
        key = (submission.quiz_id, submission.student_id)
        prev = best.get(key)
        if prev is None:
            best[key] = submission
            continue
        if submission.score > prev.score:
            best[key] = submission
        elif submission.score == prev.score and submission.attempt_number > prev.attempt_number:
            best[key] = submission
    return {sub.id for sub in best.values()}


def quiz_submission_fully_graded(submission, questions):
    manual_questions = [
        q for q in questions if (q.question_type or QuestionType.CHOICE) in MANUAL_QUESTION_TYPES
    ]
    if not manual_questions:
        return True
    scores = submission.manual_scores or {}
    for question in manual_questions:
        key = str(question.id)
        if key not in scores and question.id not in scores:
            return False
    return True
