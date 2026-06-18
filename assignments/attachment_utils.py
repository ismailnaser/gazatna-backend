from django.core.files.base import ContentFile

from assignments.models import Homework, HomeworkAttachment, QuizAnswerAttachment, SubjectMaterial, SubjectMaterialFile


def collect_uploaded_files(request):
    files = list(request.FILES.getlist("attachments"))
    legacy = request.FILES.get("attachment")
    if legacy:
        files.append(legacy)
    return [f for f in files if f]


def _file_bytes_list(files):
    return [(f.read(), f.name) for f in files]


def add_attachments_to_homework(homework, file_items, start_order=0):
    """file_items: list of (bytes, original_name)"""
    for offset, (data, name) in enumerate(file_items):
        att = HomeworkAttachment(
            homework=homework,
            original_name=name,
            sort_order=start_order + offset,
        )
        att.file.save(name, ContentFile(data), save=True)


def copy_attachments_from_homework(source_hw, target_hw):
    for att in source_hw.attachment_files.all():
        data = att.file.read()
        add_attachments_to_homework(
            target_hw,
            [(data, att.original_name or att.file.name.split("/")[-1])],
            start_order=att.sort_order,
        )


def remove_attachments(homework, attachment_ids, apply_to_group=False):
    if not attachment_ids:
        return
    ids = {str(i) for i in attachment_ids}
    targets = [homework]
    if apply_to_group and homework.group_id:
        targets = list(Homework.objects.filter(group_id=homework.group_id))

    names_to_remove = set()
    for hw in targets:
        for att in hw.attachment_files.filter(id__in=ids):
            names_to_remove.add(att.original_name or att.file.name.split("/")[-1])

    for hw in targets:
        for att in list(hw.attachment_files.all()):
            label = att.original_name or att.file.name.split("/")[-1]
            if str(att.id) in ids or label in names_to_remove:
                att.file.delete(save=False)
                att.delete()


def attachment_payload(att, request=None):
    url = att.file.url
    if request:
        url = request.build_absolute_uri(url)
    name = att.original_name or att.file.name.split("/")[-1]
    return {"id": str(att.id), "url": url, "name": name}


def homework_attachments_payload(homework, request=None):
    return [attachment_payload(att, request) for att in homework.attachment_files.all()]


def add_attachments_to_material(material, file_items, start_order=0):
    for offset, (data, name) in enumerate(file_items):
        att = SubjectMaterialFile(
            material=material,
            original_name=name,
            sort_order=start_order + offset,
        )
        att.file.save(name, ContentFile(data), save=True)


def copy_attachments_from_material(source_material, target_material):
    for att in source_material.files.all():
        data = att.file.read()
        add_attachments_to_material(
            target_material,
            [(data, att.original_name or att.file.name.split("/")[-1])],
            start_order=att.sort_order,
        )


def material_attachments_payload(material, request=None):
    return [attachment_payload(att, request) for att in material.files.all()]


def remove_material_attachments(material, attachment_ids, apply_to_group=False):
    if not attachment_ids:
        return
    ids = {str(i) for i in attachment_ids}
    targets = [material]
    if apply_to_group and material.group_id:
        targets = list(SubjectMaterial.objects.filter(group_id=material.group_id))

    names_to_remove = set()
    for row in targets:
        for att in row.files.filter(id__in=ids):
            names_to_remove.add(att.original_name or att.file.name.split("/")[-1])

    for row in targets:
        for att in list(row.files.all()):
            label = att.original_name or att.file.name.split("/")[-1]
            if str(att.id) in ids or label in names_to_remove:
                att.file.delete(save=False)
                att.delete()


def collect_quiz_essay_files(request):
    """Returns {question_id: uploaded_file} from multipart keys essayFile_<questionId>."""
    mapping = {}
    for key, uploaded in request.FILES.items():
        if not key.startswith("essayFile_"):
            continue
        qid = key[len("essayFile_") :].strip()
        if qid and uploaded:
            mapping[qid] = uploaded
    return mapping


def save_quiz_answer_attachments(submission, essay_files_by_question):
    submission.answer_attachments.all().delete()
    for qid, uploaded in essay_files_by_question.items():
        if not str(qid).isdigit():
            continue
        att = QuizAnswerAttachment(
            submission=submission,
            question_id=int(qid),
            original_name=getattr(uploaded, "name", "") or "",
        )
        att.file.save(att.original_name or "attachment", uploaded, save=True)


def quiz_answer_attachments_payload(submission, request=None):
    rows = []
    for att in submission.answer_attachments.all():
        payload = attachment_payload(att, request)
        payload["questionId"] = str(att.question_id)
        rows.append(payload)
    return rows
