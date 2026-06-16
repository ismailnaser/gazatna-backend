from rest_framework import serializers

from academics.models import ClassGradebook, Grade, SchoolClass, Student, StudentDocument, Subject, SubjectGrade
from assignments.models import Homework, HomeworkSubmission, Quiz, QuizQuestion, QuizSubmission
from content.models import (
    Accreditation,
    Activity,
    Alumni,
    NewsItem,
    Policy,
    Program,
    SchoolStat,
    SchoolValue,
)
from finance.models import FeeInstallment, FeePlan, PaymentNotice, PaymentStatus, StudentFeeBalance
from staff.models import TeacherClassAssignment, TeacherProfile
from accounts.models import User
from accounts.utils import create_auto_user, next_numeric_username


class SchoolClassSerializer(serializers.ModelSerializer):
    gradeLevel = serializers.CharField(source="grade_level", read_only=True)
    studentCount = serializers.IntegerField(source="student_count", read_only=True)
    homeroomTeacherId = serializers.SerializerMethodField()
    homeroomTeacherName = serializers.SerializerMethodField()

    class Meta:
        model = SchoolClass
        fields = [
            "id",
            "name",
            "gradeLevel",
            "section",
            "studentCount",
            "homeroomTeacherId",
            "homeroomTeacherName",
        ]

    def get_homeroomTeacherId(self, obj):
        return str(obj.homeroom_teacher_id) if obj.homeroom_teacher_id else None

    def get_homeroomTeacherName(self, obj):
        return obj.homeroom_teacher.name if obj.homeroom_teacher_id else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class SchoolClassWriteSerializer(serializers.ModelSerializer):
    gradeLevel = serializers.CharField(source="grade_level")
    name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = SchoolClass
        fields = ["id", "name", "gradeLevel", "section"]

    def validate(self, attrs):
        grade = attrs.get("grade_level", "").strip()
        section = attrs.get("section", "").strip()
        if not grade:
            raise serializers.ValidationError({"gradeLevel": "الصف الدراسي مطلوب"})
        if not section:
            raise serializers.ValidationError({"section": "الشعبة مطلوبة"})
        attrs["grade_level"] = grade
        attrs["section"] = section
        attrs["name"] = attrs.get("name") or f"{grade} - {section}"
        qs = SchoolClass.objects.filter(grade_level=grade, section=section)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {"section": f"الشعبة {section} موجودة مسبقاً في {grade}"}
            )
        return attrs

    def to_representation(self, instance):
        return SchoolClassSerializer(instance).data


class GradeSerializer(serializers.ModelSerializer):
    sectionsCount = serializers.IntegerField(source="sections_count")

    class Meta:
        model = Grade
        fields = ["id", "name", "sectionsCount"]

    def validate_sectionsCount(self, value):
        if value < 1:
            raise serializers.ValidationError("عدد الشعب يجب أن يكون 1 على الأقل")
        if value > 20:
            raise serializers.ValidationError("عدد الشعب كبير جداً")
        return value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class SubjectSerializer(serializers.ModelSerializer):
    teacherCount = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = ["id", "name", "teacherCount"]

    def get_teacherCount(self, obj):
        return obj.teachers.count()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class StudentSerializer(serializers.ModelSerializer):
    grade = serializers.CharField(source="grade_level", required=False)
    section = serializers.CharField(required=False)
    studentNumber = serializers.CharField(source="student_number", required=False)
    classId = serializers.PrimaryKeyRelatedField(
        source="school_class", queryset=SchoolClass.objects.all(), allow_null=True, required=False
    )
    username = serializers.SerializerMethodField()
    generatedPassword = serializers.SerializerMethodField()
    paymentStatus = serializers.SerializerMethodField()
    feesPaid = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    documents = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id",
            "name",
            "grade",
            "section",
            "studentNumber",
            "classId",
            "username",
            "generatedPassword",
            "documents",
            "paymentStatus",
            "feesPaid",
            "balance",
            "is_active",
        ]
        read_only_fields = ["studentNumber", "username", "generatedPassword"]

    def get_username(self, obj):
        return obj.parent.username if obj.parent_id else None

    def get_generatedPassword(self, obj):
        return getattr(obj, "_generated_password", None)

    def get_documents(self, obj):
        docs = obj.uploaded_documents.all()
        if docs.exists():
            request = self.context.get("request")
            result = []
            for d in docs:
                url = d.file.url if d.file else None
                if url and request:
                    url = request.build_absolute_uri(url)
                result.append({"id": str(d.id), "name": d.name, "url": url})
            return result
        # Fallback to legacy JSON strings
        legacy = obj.documents or []
        return [{"id": None, "name": str(x), "url": None} for x in legacy]

    def validate(self, attrs):
        school_class = attrs.get("school_class")
        if school_class:
            attrs["grade_level"] = school_class.grade_level or school_class.name
            attrs["section"] = school_class.section
        elif self.instance is None:
            raise serializers.ValidationError({"classId": "يجب اختيار فصل وشعبة"})
        return attrs

    def create(self, validated_data):
        student_number = validated_data.get("student_number") or next_numeric_username()
        while Student.objects.filter(student_number=student_number).exists():
            student_number = next_numeric_username()

        parent, password = create_auto_user(
            name=validated_data["name"],
            role=User.Role.PARENT,
            username=student_number,
        )
        validated_data["parent"] = parent
        validated_data["student_number"] = student_number
        student = Student.objects.create(**validated_data)
        student._generated_password = password
        return student

    def get_paymentStatus(self, obj):
        latest = obj.payment_notices.order_by("-date").first()
        if latest:
            return latest.status
        if hasattr(obj, "fee_balance"):
            # If the student hasn't submitted any payment notice yet, mark as unpaid.
            if float(obj.fee_balance.paid or 0) <= 0:
                return "unpaid"
            return PaymentStatus.APPROVED if obj.fee_balance.fees_paid else PaymentStatus.PENDING
        return "unpaid"

    def get_feesPaid(self, obj):
        if hasattr(obj, "fee_balance"):
            return obj.fee_balance.fees_paid
        return False

    def get_balance(self, obj):
        if hasattr(obj, "fee_balance"):
            fb = obj.fee_balance
            return {"total": float(fb.total), "paid": float(fb.paid), "remaining": float(fb.remaining)}
        return {"total": 0, "paid": 0, "remaining": 0}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        if data.get("classId") is not None:
            data["classId"] = str(data["classId"])
        return data


class SubjectGradeSerializer(serializers.ModelSerializer):
    maxScore = serializers.DecimalField(source="max_score", max_digits=5, decimal_places=2)

    class Meta:
        model = SubjectGrade
        fields = ["id", "subject", "score", "maxScore", "note"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["score"] = float(data["score"])
        data["maxScore"] = float(data["maxScore"])
        return data


class ClassGradebookSerializer(serializers.ModelSerializer):
    classId = serializers.PrimaryKeyRelatedField(source="school_class", read_only=True)
    studentId = serializers.PrimaryKeyRelatedField(source="student", read_only=True)

    class Meta:
        model = ClassGradebook
        fields = ["id", "studentId", "classId", "score", "note"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["studentId"] = str(data["studentId"])
        data["classId"] = str(data["classId"])
        if data["score"] is not None:
            data["score"] = float(data["score"])
        return data


class ClassStudentSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    grade = serializers.JSONField()
    note = serializers.CharField()


class TeacherProfileSerializer(serializers.ModelSerializer):
    userId = serializers.PrimaryKeyRelatedField(
        source="user", queryset=User.objects.all(),
        allow_null=True, required=False
    )
    username = serializers.SerializerMethodField()
    generatedPassword = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()
    subjects = serializers.SerializerMethodField()
    subjectIds = serializers.SerializerMethodField()
    imageUrl = serializers.SerializerMethodField()
    imageGradient = serializers.CharField(source="image_gradient", required=False, allow_blank=True)
    classIds = serializers.SerializerMethodField()

    class Meta:
        model = TeacherProfile
        fields = [
            "id",
            "userId",
            "username",
            "generatedPassword",
            "name",
            "subject",
            "subjects",
            "subjectIds",
            "experience",
            "bio",
            "image",
            "imageUrl",
            "imageGradient",
            "is_public",
            "classIds",
        ]
        extra_kwargs = {"image": {"write_only": True}}

    def get_imageUrl(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = obj.image.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def _subject_names(self, obj):
        return [s.name for s in obj.teaching_subjects.all()]

    def get_subject(self, obj):
        return "، ".join(self._subject_names(obj))

    def get_subjects(self, obj):
        return self._subject_names(obj)

    def get_subjectIds(self, obj):
        return [str(s.id) for s in obj.teaching_subjects.all()]

    def get_username(self, obj):
        return obj.user.username if obj.user_id else None

    def get_generatedPassword(self, obj):
        return getattr(obj, "_generated_password", None)

    def get_classIds(self, obj):
        return [str(a.school_class_id) for a in obj.class_assignments.select_related("school_class")]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        if data.get("userId") is not None:
            data["userId"] = str(data["userId"])
        data.pop("image", None)
        return data


class TeacherWriteSerializer(serializers.ModelSerializer):
    userId = serializers.PrimaryKeyRelatedField(
        source="user",
        queryset=User.objects.all(),
        allow_null=True,
        required=False,
    )
    subjectIds = serializers.PrimaryKeyRelatedField(
        source="teaching_subjects",
        queryset=Subject.objects.all(),
        many=True,
    )
    subject = serializers.SerializerMethodField()
    subjects = serializers.SerializerMethodField()
    imageGradient = serializers.CharField(source="image_gradient", required=False, allow_blank=True)
    classIds = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)

    class Meta:
        model = TeacherProfile
        fields = [
            "id",
            "userId",
            "name",
            "subject",
            "subjects",
            "subjectIds",
            "experience",
            "bio",
            "image",
            "imageGradient",
            "classIds",
        ]
        extra_kwargs = {"image": {"write_only": True}}

    def get_subject(self, obj):
        return "، ".join(s.name for s in obj.teaching_subjects.all())

    def get_subjects(self, obj):
        return [s.name for s in obj.teaching_subjects.all()]

    def validate(self, attrs):
        if self.instance is None and not attrs.get("teaching_subjects"):
            raise serializers.ValidationError({"subjectIds": "يجب اختيار مادة واحدة على الأقل"})
        return attrs

    def _set_classes(self, teacher, class_ids):
        TeacherClassAssignment.objects.filter(teacher=teacher).delete()
        for class_id in class_ids or []:
            TeacherClassAssignment.objects.create(teacher=teacher, school_class_id=class_id)

    def create(self, validated_data):
        validated_data.pop("user", None)
        class_ids = validated_data.pop("classIds", [])
        subjects = validated_data.pop("teaching_subjects", [])
        user, password = create_auto_user(
            name=validated_data["name"],
            role=User.Role.TEACHER,
        )
        validated_data["user"] = user
        teacher = TeacherProfile.objects.create(**validated_data)
        teacher.teaching_subjects.set(subjects)
        self._set_classes(teacher, class_ids)
        teacher._generated_password = password
        return teacher

    def update(self, instance, validated_data):
        class_ids = validated_data.pop("classIds", None)
        subjects = validated_data.pop("teaching_subjects", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if subjects is not None:
            instance.teaching_subjects.set(subjects)
        if class_ids is not None:
            self._set_classes(instance, class_ids)
        return instance

    def to_representation(self, instance):
        return TeacherProfileSerializer(instance).data


class QuizQuestionSerializer(serializers.ModelSerializer):
    correctIndex = serializers.IntegerField(source="correct_index")

    class Meta:
        model = QuizQuestion
        fields = ["id", "prompt", "options", "correctIndex", "order"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class HomeworkSerializer(serializers.ModelSerializer):
    classId = serializers.PrimaryKeyRelatedField(source="school_class", queryset=SchoolClass.objects.all())
    teacherId = serializers.PrimaryKeyRelatedField(
        source="teacher", queryset=TeacherProfile.objects.all(), required=False
    )
    dueDate = serializers.DateField(source="due_date", format="%Y-%m-%d")
    createdAt = serializers.DateTimeField(source="created_at", format="%Y-%m-%d", read_only=True)

    class Meta:
        model = Homework
        fields = ["id", "classId", "teacherId", "title", "description", "dueDate", "status", "createdAt"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["classId"] = str(data["classId"])
        data["teacherId"] = str(data["teacherId"])
        return data


class HomeworkSubmissionSerializer(serializers.ModelSerializer):
    homeworkId = serializers.PrimaryKeyRelatedField(source="homework", queryset=Homework.objects.all())
    studentId = serializers.PrimaryKeyRelatedField(source="student", queryset=Student.objects.all())
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True)

    class Meta:
        model = HomeworkSubmission
        fields = ["id", "homeworkId", "studentId", "content", "submittedAt"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["homeworkId"] = str(data["homeworkId"])
        data["studentId"] = str(data["studentId"])
        return data


class QuizSerializer(serializers.ModelSerializer):
    classId = serializers.PrimaryKeyRelatedField(source="school_class", queryset=SchoolClass.objects.all())
    teacherId = serializers.PrimaryKeyRelatedField(
        source="teacher", queryset=TeacherProfile.objects.all(), required=False
    )
    dueDate = serializers.DateField(source="due_date", format="%Y-%m-%d")
    startAt = serializers.DateTimeField(source="start_at")
    durationMinutes = serializers.IntegerField(source="duration_minutes")
    createdAt = serializers.DateTimeField(source="created_at", format="%Y-%m-%d", read_only=True)
    questions = QuizQuestionSerializer(many=True, required=False)

    class Meta:
        model = Quiz
        fields = [
            "id", "classId", "teacherId", "title", "description", "dueDate",
            "startAt", "durationMinutes", "status", "questions", "createdAt",
        ]

    def create(self, validated_data):
        questions_data = validated_data.pop("questions", [])
        quiz = Quiz.objects.create(**validated_data)
        for i, q in enumerate(questions_data):
            QuizQuestion.objects.create(quiz=quiz, order=i, **q)
        return quiz

    def update(self, instance, validated_data):
        questions_data = validated_data.pop("questions", None)
        instance = super().update(instance, validated_data)
        if questions_data is not None:
            instance.questions.all().delete()
            for i, q in enumerate(questions_data):
                QuizQuestion.objects.create(quiz=instance, order=i, **q)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["classId"] = str(data["classId"])
        data["teacherId"] = str(data["teacherId"])
        return data


class QuizSubmissionSerializer(serializers.ModelSerializer):
    quizId = serializers.PrimaryKeyRelatedField(source="quiz", queryset=Quiz.objects.all())
    studentId = serializers.PrimaryKeyRelatedField(source="student", queryset=Student.objects.all())
    maxScore = serializers.DecimalField(source="max_score", max_digits=5, decimal_places=2)
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True)
    timeSpentSeconds = serializers.IntegerField(source="time_spent_seconds")

    class Meta:
        model = QuizSubmission
        fields = ["id", "quizId", "studentId", "answers", "score", "maxScore", "submittedAt", "timeSpentSeconds"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["quizId"] = str(data["quizId"])
        data["studentId"] = str(data["studentId"])
        data["score"] = float(data["score"])
        data["maxScore"] = float(data["maxScore"])
        return data


class PaymentNoticeSerializer(serializers.ModelSerializer):
    studentName = serializers.CharField(source="student.name", read_only=True)
    declaredAmount = serializers.DecimalField(source="declared_amount", max_digits=10, decimal_places=2, read_only=True)
    receiptUrl = serializers.SerializerMethodField()

    class Meta:
        model = PaymentNotice
        fields = ["id", "studentName", "declaredAmount", "amount", "date", "status", "note", "receiptUrl"]

    def get_receiptUrl(self, obj):
        if not obj.receipt:
            return None
        request = self.context.get("request")
        url = obj.receipt.url
        return request.build_absolute_uri(url) if request else url

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["declaredAmount"] = float(data["declaredAmount"])
        data["amount"] = float(data["amount"])
        data["date"] = str(data["date"])
        return data


class FinanceNoticeSerializer(serializers.Serializer):
    id = serializers.CharField()
    studentId = serializers.CharField()
    studentName = serializers.CharField()
    declaredAmount = serializers.FloatField()
    amount = serializers.FloatField()
    status = serializers.CharField()
    date = serializers.CharField()
    note = serializers.CharField(allow_blank=True, required=False)
    receiptUrl = serializers.CharField(allow_null=True, required=False)


class FeeInstallmentSerializer(serializers.ModelSerializer):
    startDate = serializers.DateField(source="start_date", allow_null=True, required=False)
    endDate = serializers.DateField(source="end_date", allow_null=True, required=False)

    class Meta:
        model = FeeInstallment
        fields = ["id", "order", "amount", "startDate", "endDate"]
        read_only_fields = ["id"]

    def to_internal_value(self, data):
        # Convert empty strings to None so DateField doesn't reject them
        mutable = dict(data)
        if mutable.get("startDate") == "":
            mutable["startDate"] = None
        if mutable.get("endDate") == "":
            mutable["endDate"] = None
        return super().to_internal_value(mutable)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if data.get("id") is not None:
            data["id"] = str(data["id"])
        data["amount"] = float(data["amount"])
        data["startDate"] = str(data["startDate"]) if data["startDate"] else None
        data["endDate"] = str(data["endDate"]) if data["endDate"] else None
        return data


class FeePlanSerializer(serializers.ModelSerializer):
    gradeIds = serializers.PrimaryKeyRelatedField(source="grades", queryset=Grade.objects.all(), many=True)
    installmentsCount = serializers.IntegerField(source="installments_count")
    totalAmount = serializers.DecimalField(source="total_amount", max_digits=10, decimal_places=2)
    isActive = serializers.BooleanField(source="is_active", required=False, default=True)
    gradeNames = serializers.SerializerMethodField()
    installments = FeeInstallmentSerializer(many=True)

    class Meta:
        model = FeePlan
        fields = [
            "id",
            "name",
            "totalAmount",
            "installmentsCount",
            "isActive",
            "gradeIds",
            "gradeNames",
            "installments",
        ]

    def get_gradeNames(self, obj):
        return list(obj.grades.values_list("name", flat=True))

    def _save_installments(self, plan, installments_data):
        plan.installments.all().delete()
        for row in installments_data:
            FeeInstallment.objects.create(
                fee_plan=plan,
                order=row["order"],
                amount=row["amount"],
                start_date=row.get("start_date") or None,
                end_date=row.get("end_date") or None,
            )

    def create(self, validated_data):
        installments_data = validated_data.pop("installments", [])
        grades = validated_data.pop("grades", [])
        plan = FeePlan.objects.create(**validated_data)
        if grades:
            plan.grades.set(grades)
        self._save_installments(plan, installments_data)
        return plan

    def update(self, instance, validated_data):
        installments_data = validated_data.pop("installments", None)
        grades = validated_data.pop("grades", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if grades is not None:
            instance.grades.set(grades)
        if installments_data is not None:
            self._save_installments(instance, installments_data)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["totalAmount"] = float(data["totalAmount"])
        data["gradeIds"] = [str(gid) for gid in data["gradeIds"]]
        return data


class NewsItemSerializer(serializers.ModelSerializer):
    imageUrl = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()

    class Meta:
        model = NewsItem
        fields = [
            "id", "title", "description", "body", "date", "category",
            "gradient", "featured", "image", "imageUrl", "images",
        ]
        extra_kwargs = {"image": {"write_only": True}}

    def _absolute_url(self, request, url):
        if request and url:
            return request.build_absolute_uri(url)
        return url

    def _serialize_image(self, request, image_obj):
        if not image_obj or not image_obj.file:
            return None
        return {
            "id": str(image_obj.id),
            "url": self._absolute_url(request, image_obj.file.url),
            "isCover": bool(image_obj.is_cover),
        }

    def get_images(self, obj):
        request = self.context.get("request")
        gallery = list(obj.images.all())
        if gallery:
            return [
                serialized
                for image in gallery
                if image.file and (serialized := self._serialize_image(request, image))
            ]
        if obj.image:
            return [{
                "id": None,
                "url": self._absolute_url(request, obj.image.url),
                "isCover": True,
            }]
        return []

    def get_imageUrl(self, obj):
        request = self.context.get("request")
        cover = obj.images.filter(is_cover=True).first() or obj.images.order_by("order", "id").first()
        if cover and cover.file:
            return self._absolute_url(request, cover.file.url)
        if obj.image:
            return self._absolute_url(request, obj.image.url)
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        data["date"] = str(data["date"])
        data.pop("image", None)
        return data


class ProgramSerializer(serializers.ModelSerializer):
    desc = serializers.CharField(source="description")

    class Meta:
        model = Program
        fields = ["id", "title", "grades", "desc", "features", "accent"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class ActivitySerializer(serializers.ModelSerializer):
    desc = serializers.CharField(source="description")

    class Meta:
        model = Activity
        fields = ["id", "title", "desc"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class AlumniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alumni
        fields = ["id", "name", "year", "achievement"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class PolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = Policy
        fields = ["id", "title", "text"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class AccreditationSerializer(serializers.ModelSerializer):
    desc = serializers.CharField(source="description")

    class Meta:
        model = Accreditation
        fields = ["id", "name", "desc"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class SchoolStatSerializer(serializers.ModelSerializer):
    iconBg = serializers.CharField(source="icon_bg")
    iconColor = serializers.CharField(source="icon_color")
    iconName = serializers.CharField(source="icon_name")

    class Meta:
        model = SchoolStat
        fields = ["id", "label", "value", "iconName", "iconBg", "iconColor"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = instance.key
        return data


class SchoolValueSerializer(serializers.ModelSerializer):
    desc = serializers.CharField(source="description")
    num = serializers.CharField(source="number")

    class Meta:
        model = SchoolValue
        fields = ["id", "title", "desc", "num"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["id"] = str(data["id"])
        return data


class ParentAlertSerializer(serializers.Serializer):
    id = serializers.CharField()
    text = serializers.CharField()
    type = serializers.CharField()


class ParentChildSerializer(serializers.Serializer):
    parentUserId = serializers.CharField()
    studentId = serializers.CharField()
    classId = serializers.CharField()
    name = serializers.CharField()
